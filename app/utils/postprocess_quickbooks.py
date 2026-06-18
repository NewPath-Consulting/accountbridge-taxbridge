from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def currency_symbol(currency: Optional[str]) -> str:
    """Map QuickBooks currency metadata to a display symbol."""
    if not currency:
        return "$"
    code = str(currency).strip().upper()
    if code in ("USD", "US$", "US DOLLAR", "US DOLLARS"):
        return "$"
    if code in ("INR", "₹", "RUPEES", "RUPEE"):
        return "₹"
    return "$"


def _format_amount(symbol: str, total: float) -> str:
    return f"{symbol}{total:,.2f}"


def _match_summary_total(rows: List[Dict[str, Any]], *labels: str) -> Optional[float]:
    """Find a summary row total by case-insensitive account label (labels are priority-ordered)."""
    for label in labels:
        target = label.lower()
        for entry in rows:
            if entry.get("row_type") != "summary":
                continue
            account = QuickBooksReportParser._extract_account_value(entry.get("values") or {})
            if not account:
                continue
            if str(account).strip().lower() == target:
                total = QuickBooksReportParser._extract_total_value(entry.get("values") or {})
                if isinstance(total, (int, float)):
                    return float(total)
    return None


def extract_quickbooks_totals(
    rows: List[Dict[str, Any]],
    report_name: Optional[str] = None,
) -> Dict[str, Optional[float]]:
    """Extract headline totals from postprocessed QuickBooks rows."""
    name = (report_name or "").lower()
    totals: Dict[str, Optional[float]] = {
        "total_income": None,
        "total_expenses": None,
        "net_income": None,
        "total_assets": None,
        "total_liabilities": None,
        "net_assets": None,
    }

    if "profit" in name or name in ("profitandloss", "profit and loss"):
        totals["total_income"] = _match_summary_total(rows, "Total Income", "Total Revenue")
        totals["total_expenses"] = _match_summary_total(rows, "Total Expenses")
        totals["net_income"] = _match_summary_total(rows, "Net Income", "Net Operating Income")
    elif "balance" in name:
        totals["total_assets"] = _match_summary_total(rows, "TOTAL ASSETS", "Total Assets")
        totals["total_liabilities"] = _match_summary_total(
            rows, "Total Liabilities", "TOTAL LIABILITIES"
        )
        totals["net_assets"] = _match_summary_total(
            rows,
            "TOTAL LIABILITIES AND EQUITY",
            "Total Equity",
            "Net Assets",
            "Total Net Assets",
        )
        if totals["net_assets"] is None and totals["total_assets"] is not None:
            liabilities = totals["total_liabilities"] or 0.0
            totals["net_assets"] = totals["total_assets"] - liabilities

    return totals


def _top_quickbooks_rows(rows: List[Dict[str, Any]], *, limit: int = 50) -> List[Dict[str, Any]]:
    """Return a capped list of row summaries for LLM prompts."""
    top: List[Dict[str, Any]] = []
    for entry in rows[:limit]:
        values = entry.get("values") or {}
        top.append(
            {
                "hierarchy_path": entry.get("hierarchy_path"),
                "row_type": entry.get("row_type"),
                "account": QuickBooksReportParser._extract_account_value(values),
                "total": QuickBooksReportParser._extract_total_value(values),
            }
        )
    return top


@dataclass
class ReportMetadata:
    report_name: str
    start_period: Optional[str]
    end_period: Optional[str]
    currency: Optional[str]
    report_basis: Optional[str]


@dataclass
class ReportRow:
    report_name: str
    row_type: str
    hierarchy: List[str]
    hierarchy_path: str
    values: Dict[str, Any]


class QuickBooksReportParser:
    """
    Generic parser for QuickBooks Financial Reports.

    Supports:
    - Balance Sheet
    - Profit & Loss
    - Trial Balance
    - Cash Flow
    - Budget vs Actual
    - Class Reports
    - Department Reports
    """

    def __init__(self, report_json: Dict[str, Any]):

        self.report = report_json

        self.metadata = self._extract_metadata()

        self.columns = self._extract_columns()

        self.records: List[ReportRow] = []

    def parse(self) -> List[ReportRow]:

        rows = (
            self.report
            .get("Rows", {})
            .get("Row", [])
        )

        for row in rows:
            self._walk(
                node=row,
                hierarchy=[]
            )

        return self.records

    def to_dict(self) -> List[Dict]:

        return [asdict(record) for record in self.records]

    def _extract_metadata(self) -> ReportMetadata:

        header = self.report.get("Header", {})

        return ReportMetadata(
            report_name=header.get("ReportName"),
            start_period=header.get("StartPeriod"),
            end_period=header.get("EndPeriod"),
            currency=header.get("Currency"),
            report_basis=header.get("ReportBasis"),
        )

    def _extract_columns(self) -> List[str]:

        columns = []

        for idx, column in enumerate(
            self.report
            .get("Columns", {})
            .get("Column", [])
        ):

            key = None

            for meta in column.get("MetaData", []):

                if meta.get("Name") == "ColKey":
                    key = meta.get("Value")
                    break

            columns.append(
                key
                or column.get("ColTitle")
                or f"column_{idx}"
            )

        return columns

    def _walk(
        self,
        node: Dict[str, Any],
        hierarchy: List[str]
    ) -> None:

        row_type = node.get("type")

        if row_type == "Section":

            self._process_section(
                node=node,
                hierarchy=hierarchy
            )

        elif row_type == "Data":

            self._process_data(
                node=node,
                hierarchy=hierarchy
            )

    def _process_section(
        self,
        node: Dict[str, Any],
        hierarchy: List[str]
    ):

        section_name = self._extract_header(node)

        current_hierarchy = hierarchy.copy()

        if section_name:
            current_hierarchy.append(section_name)

        summary = node.get("Summary")

        if summary:

            self.records.append(
                ReportRow(
                    report_name=self.metadata.report_name,
                    row_type="summary",
                    hierarchy=current_hierarchy,
                    hierarchy_path=" > ".join(current_hierarchy),
                    values=self._extract_values(summary),
                )
            )

        children = (
            node.get("Rows", {})
            .get("Row", [])
        )

        for child in children:

            self._walk(
                node=child,
                hierarchy=current_hierarchy
            )

    def _process_data(
        self,
        node: Dict[str, Any],
        hierarchy: List[str]
    ):

        self.records.append(
            ReportRow(
                report_name=self.metadata.report_name,
                row_type="data",
                hierarchy=hierarchy,
                hierarchy_path=" > ".join(hierarchy),
                values=self._extract_values(node),
            )
        )

    def _extract_header(
        self,
        node: Dict[str, Any]
    ) -> Optional[str]:

        header = node.get("Header", {})

        col_data = header.get("ColData", [])

        if not col_data:
            return None

        return col_data[0].get("value")

    def _extract_values(
        self,
        node: Dict[str, Any]
    ) -> Dict[str, Any]:

        values = {}

        col_data = node.get("ColData", [])

        for idx, cell in enumerate(col_data):

            column_name = (
                self.columns[idx]
                if idx < len(self.columns)
                else f"column_{idx}"
            )

            value = cell.get("value")

            values[column_name] = {
                "value": self._normalize_value(value),
                "id": cell.get("id"),
            }

        return values

    @staticmethod
    def _normalize_value(value: Any) -> Any:

        if value is None:
            return None

        if value == "":
            return None

        if isinstance(value, str):

            cleaned = value.replace(",", "")

            try:
                return float(cleaned)
            except ValueError:
                return value

        return value

    @staticmethod
    def _extract_account_value(values: Dict[str, Any]) -> Any:
        account_cell = values.get("account")
        if isinstance(account_cell, dict):
            return account_cell.get("value")
        if values:
            first = next(iter(values.values()))
            if isinstance(first, dict):
                return first.get("value")
        return None

    @staticmethod
    def _extract_total_value(values: Dict[str, Any]) -> Any:
        total_cell = values.get("total")
        if isinstance(total_cell, dict):
            return total_cell.get("value")
        for key, cell in values.items():
            if key == "account" or not isinstance(cell, dict):
                continue
            amount = cell.get("value")
            if isinstance(amount, (int, float)):
                return amount
        return None

    @staticmethod
    def format_balance_sheet(
        json_data: List[Dict[str, Any]],
        *,
        currency: Optional[str] = None,
    ) -> str:
        symbol = currency_symbol(currency)
        organized_data: Dict[str, Any] = {}

        for entry in json_data:
            hierarchy_path = entry["hierarchy_path"]
            account = QuickBooksReportParser._extract_account_value(entry["values"])
            total = QuickBooksReportParser._extract_total_value(entry["values"])
            row_type = entry["row_type"]

            parts = hierarchy_path.split(" > ")
            current_level = organized_data

            for part in parts:
                if part not in current_level:
                    current_level[part] = {}
                current_level = current_level[part]

            if row_type == "summary":
                current_level["_summary"] = {"account": account, "total": total}
            else:
                if "_details" not in current_level:
                    current_level["_details"] = []
                current_level["_details"].append({"account": account, "total": total})

        def format_hierarchy(data: Dict[str, Any], indent: int = 0) -> List[str]:
            output: List[str] = []
            for key, value in data.items():
                if key == "_summary":
                    total = value["total"]
                    if total is not None:
                        output.append(
                            "  " * indent
                            + f"**{value['account']}:** {_format_amount(symbol, total)}"
                        )
                    else:
                        output.append(
                            "  " * indent + f"**{value['account']}:** (No value)"
                        )
                elif key == "_details":
                    for detail in value:
                        total = detail["total"]
                        if total is not None:
                            output.append(
                                "  " * (indent + 1)
                                + f"- {detail['account']}: {_format_amount(symbol, total)}"
                            )
                        else:
                            output.append(
                                "  " * (indent + 1)
                                + f"- {detail['account']}: (No value)"
                            )
                else:
                    output.append("  " * indent + f"#### {key}")
                    output.extend(format_hierarchy(value, indent + 1))
            return output

        formatted_output = ["# Balance Sheet", ""] + format_hierarchy(organized_data)
        return "\n".join(formatted_output)

    @staticmethod
    def format_financial_report(
        json_data: List[Dict[str, Any]],
        report_name: Optional[str] = None,
        *,
        currency: Optional[str] = None,
    ) -> str:
        """
        Convert parsed QuickBooks report rows into a readable hierarchical format.
        """
        if report_name is None:
            report_name = json_data[0]["report_name"] if json_data else "Financial Report"

        symbol = currency_symbol(currency)
        organized_data: Dict[str, Any] = {}

        for entry in json_data:
            hierarchy_path = entry.get("hierarchy_path", "")
            account = QuickBooksReportParser._extract_account_value(entry["values"])
            total = QuickBooksReportParser._extract_total_value(entry["values"])
            row_type = entry["row_type"]

            if not hierarchy_path:
                if "_top_level" not in organized_data:
                    organized_data["_top_level"] = []
                organized_data["_top_level"].append(
                    {"account": account, "total": total, "row_type": row_type}
                )
                continue

            parts = hierarchy_path.split(" > ")
            current_level = organized_data

            for part in parts:
                if part not in current_level:
                    current_level[part] = {}
                current_level = current_level[part]

            if row_type == "summary":
                current_level["_summary"] = {"account": account, "total": total}
            else:
                if "_details" not in current_level:
                    current_level["_details"] = []
                current_level["_details"].append({"account": account, "total": total})

        def format_hierarchy(data: Dict[str, Any], indent: int = 0) -> List[str]:
            output: List[str] = []
            for key, value in data.items():
                if key == "_summary":
                    total = value["total"]
                    if total is not None:
                        output.append(
                            "  " * indent
                            + f"**{value['account']}:** {_format_amount(symbol, total)}"
                        )
                    else:
                        output.append(
                            "  " * indent + f"**{value['account']}:** (No value)"
                        )
                elif key == "_details":
                    for detail in value:
                        total = detail["total"]
                        if total is not None:
                            output.append(
                                "  " * (indent + 1)
                                + f"- {detail['account']}: {_format_amount(symbol, total)}"
                            )
                        else:
                            output.append(
                                "  " * (indent + 1)
                                + f"- {detail['account']}: (No value)"
                            )
                elif key == "_top_level":
                    for item in value:
                        total = item["total"]
                        if total is not None:
                            output.append(
                                "  " * indent
                                + f"**{item['account']}:** {_format_amount(symbol, total)}"
                            )
                        else:
                            output.append(
                                "  " * indent + f"**{item['account']}:** (No value)"
                            )
                else:
                    output.append("  " * indent + f"#### {key}")
                    output.extend(format_hierarchy(value, indent + 1))
            return output

        header = f"# {report_name}\n"
        formatted_output = [header] + format_hierarchy(organized_data)
        return "\n".join(formatted_output)

    def format_report(self) -> str:
        """Format parsed report rows for LLM consumption."""
        rows = self.to_dict()
        currency = self.metadata.currency
        if self.metadata.report_name == "BalanceSheet":
            return self.format_balance_sheet(rows, currency=currency)
        return self.format_financial_report(rows, self.metadata.report_name, currency=currency)


def postprocess_quickbooks_report(report_json: Dict[str, Any]) -> Dict[str, Any]:
    """Parse raw QuickBooks report JSON into metadata and flat structured rows."""
    if report_json.get("Fault"):
        return {
            "metadata": None,
            "rows": [],
            "error": report_json.get("Fault"),
        }

    parser = QuickBooksReportParser(report_json)
    parser.parse()
    rows = parser.to_dict()
    return {
        "metadata": asdict(parser.metadata),
        "rows": rows,
        "formatted_report": parser.format_report(),
    }


def postprocess_quickbooks_data(quickbooks_data: Dict[str, Any]) -> Dict[str, Any]:
    """Clean Profit & Loss and Balance Sheet reports for downstream LLM use."""
    processed = {
        "profit_and_loss": postprocess_quickbooks_report(
            quickbooks_data.get("profit_and_loss") or {}
        ),
        "balance_sheet": postprocess_quickbooks_report(
            quickbooks_data.get("balance_sheet") or {}
        ),
    }
    for report_key, report in processed.items():
        row_count = len(report.get("rows") or [])
        formatted_len = len(report.get("formatted_report") or "")
        logger.info(
            "Postprocessed QuickBooks %s rows=%s formatted_chars=%s",
            report_key,
            row_count,
            formatted_len,
        )
    return processed


if __name__ == "__main__":
    # Example main block to test the QuickBooksReportParser
    # No argparse; use hardcoded input values.
    input_path = Path("data/quickbooks/balance-sheet.json")
    output_path = "data/quickbooks/balance-sheet-structured.json"  # Set to a string path like "output.json" to write structured output

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        report_json = json.load(f)

    parser_instance = QuickBooksReportParser(report_json)
    records = parser_instance.parse()
    structured_data = parser_instance.to_dict()

    print("Parsed report metadata:")
    print(parser_instance.metadata)
    print("\nSample of parsed report rows:")
    for rec in structured_data[:5]:
        print(json.dumps(rec, indent=2))

    formatted_report = parser_instance.format_report()
    print("\nFormatted report preview:")
    print(formatted_report[:2000])
    if len(formatted_report) > 2000:
        print("... (truncated)")

    if output_path:
        with open(output_path, "w", encoding="utf-8") as outf:
            json.dump(structured_data, outf, indent=2, ensure_ascii=False)
        print(f"\nStructured data written to {output_path}")

        formatted_output_path = Path(str(output_path).replace(".json", "-formatted.txt"))
        formatted_output_path.write_text(formatted_report, encoding="utf-8")
        print(f"Formatted report written to {formatted_output_path}")
    else:
        print("\nNo output path provided; structured data not written to file.")