"""Form-variant routing harness over ProPublica filings.

ProPublica's organization endpoint returns every extracted Form 990 and 990-EZ an
organization has filed, with line-item data. That is a labeled dataset for
form-variant routing: the inputs (gross receipts, total assets, age, multi-year
history) come from the filing, and the label is the form the organization
actually filed. No ledger is synthesized, so there is no circularity.

Gross receipts is the IRS definition, "the total amounts the organization
received from all sources during its tax year, without subtracting any costs or
expenses" (Form 990 instructions, glossary). On the filed forms it is:

    Form 990, item G / Part VIII: line 12 + 6b(i) + 6b(ii) + 7b(i) + 7b(ii) + 8b + 9b + 10b
    Form 990-EZ, item L:          line 9 + 5b + 6c + 7b

ProPublica exposes these lines under the IRS SOI extract element names:

    Form 990:    totrevenue, rntlexpnsreal, rntlexpnsprsnl, cstbasisecur, cstbasisothr,
                 lessdirfndrsng, lessdirgaming, lesscstofgoods
    Form 990-EZ: totrevnue, basisalesexpnsothr, direxpns, costgoodsold

Two limits of the data source:

    * 990-N filers are not in ProPublica ("Small organizations filing a Form 990N
      e-Postcard are not included in this data"). Every label is 990 or 990-EZ.
      A 990-N prediction can therefore never be confirmed by a filing; it can
      only be scored as "filed a fuller form than required", which the IRS permits.
    * Age is derived from the Business Master File ruling date, which is the
      IRS recognition date, not the formation date. It is a lower bound on the
      organization's age. Records with ruling-date age under three years are
      counted separately in the summary because the 990-N tier depends on age.
"""

from __future__ import annotations

import calendar
import inspect
import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

# ---- IRS thresholds ---------------------------------------------------------------

EZ_GROSS_RECEIPTS_LIMIT = 200_000  # Form 990-EZ item L: file Form 990 if gross receipts >= this
EZ_TOTAL_ASSETS_LIMIT = 500_000  # Form 990-EZ item L: file Form 990 if total assets >= this
N_ESTABLISHED_LIMIT = 50_000  # Form 990-N: gross receipts normally <= this (organizations 3+ years old)
BOUNDARY_MARGIN = 0.05  # within +/-5% of a threshold is flagged as near-boundary

FORM_990 = "990"
FORM_990EZ = "990-EZ"
FORM_990N = "990-N"
FORM_990PF = "990-PF"
RANK = {FORM_990N: 0, FORM_990EZ: 1, FORM_990: 2}

FORMTYPE_LABELS = {0: FORM_990, 1: FORM_990EZ, 2: FORM_990PF}

# Outcome classes
MATCH = "match"
PERMITTED_UPGRADE = "permitted_upgrade"  # filed a fuller form than the router requires (IRS permits this)
UNDER_FILED = "under_filed"  # filed a lesser form than the router requires (real disagreement)
REVIEW = "review"  # router held the filing for preparer review
NO_PREDICTION = "no_prediction"

# Attribution of disagreements
FILER_INELIGIBLE_BY_OWN_FIGURES = "filer_ineligible_by_own_figures"
ROUTER_DISAGREES_WITH_FORM_TEST = "router_disagrees_with_form_test"
N_ELIGIBLE_FILED_FULLER_FORM = "990n_eligible_filed_fuller_form"  # unverifiable: voluntary or router over-eligibility
EZ_ELIGIBLE_FILED_FULL_990 = "ez_eligible_filed_full_990"


# ---- Records -------------------------------------------------------------------------


@dataclass(frozen=True)
class FilingRecord:
    ein: int
    name: str
    tax_prd: int  # YYYYMM, month the fiscal year ended
    tax_year: int
    form_filed: str  # FORM_990 or FORM_990EZ
    total_revenue: float
    gross_receipts: float
    total_assets_end: Optional[float]
    age_years: Optional[float]  # at fiscal year end, from BMF ruling_date
    ruling_date: Optional[str]
    subsection_code: Optional[int]
    filing_requirement_code: Optional[int]  # BMF FILING_REQ_CD; 2 = currently a 990-N filer
    history: Tuple[float, ...]  # gross receipts, most recent first, consecutive periods, up to 3
    history_complete: bool  # three consecutive periods present

    @property
    def gross_receipts_addbacks(self) -> float:
        return self.gross_receipts - self.total_revenue


@dataclass
class BuildReport:
    records: List[FilingRecord] = field(default_factory=list)
    skipped_pf: int = 0
    skipped_missing_data: int = 0


@dataclass(frozen=True)
class Prediction:
    variant: Optional[str]  # FORM_990N, FORM_990EZ, FORM_990, or None
    review: bool = False
    reason: Optional[str] = None


@dataclass
class EvaluationResult:
    record: FilingRecord
    prediction: Prediction
    outcome: str
    attribution: Optional[str]
    near_boundary: Tuple[str, ...]


# ---- Gross receipts ----------------------------------------------------------------


def _num(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def form_label(formtype: Any) -> Optional[str]:
    try:
        return FORMTYPE_LABELS.get(int(formtype))
    except (TypeError, ValueError):
        return None


def gross_receipts_990(filing: Dict) -> Optional[float]:
    """Form 990 gross receipts: Part VIII line 12 plus lines 6b, 7b, 8b, 9b, 10b."""
    if filing.get("totrevenue") is None:
        return None
    return (
        _num(filing.get("totrevenue"))
        + _num(filing.get("rntlexpnsreal"))
        + _num(filing.get("rntlexpnsprsnl"))
        + _num(filing.get("cstbasisecur"))
        + _num(filing.get("cstbasisothr"))
        + _num(filing.get("lessdirfndrsng"))
        + _num(filing.get("lessdirgaming"))
        + _num(filing.get("lesscstofgoods"))
    )


def gross_receipts_990ez(filing: Dict) -> Optional[float]:
    """Form 990-EZ gross receipts: item L, line 9 plus lines 5b, 6c, 7b."""
    total = filing.get("totrevnue")
    if total is None:
        total = filing.get("totrevenue")
    if total is None:
        return None
    return (
        _num(total)
        + _num(filing.get("basisalesexpnsothr"))
        + _num(filing.get("direxpns"))
        + _num(filing.get("costgoodsold"))
    )


def gross_receipts(filing: Dict) -> Optional[float]:
    label = form_label(filing.get("formtype"))
    if label == FORM_990:
        return gross_receipts_990(filing)
    if label == FORM_990EZ:
        return gross_receipts_990ez(filing)
    return None


# ---- Periods and age -----------------------------------------------------------------


def tax_period_end(tax_prd: int) -> date:
    year, month = divmod(int(tax_prd), 100)
    return date(year, month, calendar.monthrange(year, month)[1])


def previous_period(tax_prd: int) -> int:
    return int(tax_prd) - 100


def age_years_at(ruling_date: Optional[str], tax_prd: int) -> Optional[float]:
    if not ruling_date:
        return None
    try:
        ruled = date.fromisoformat(str(ruling_date)[:10])
    except ValueError:
        return None
    return (tax_period_end(tax_prd) - ruled).days / 365.25


# ---- Dataset construction ----------------------------------------------------------


def build_records(org_json: Dict) -> BuildReport:
    """One FilingRecord per extracted 990 or 990-EZ, most recent first."""
    org = org_json.get("organization") or {}
    report = BuildReport()
    receipts_by_period: Dict[int, float] = {}
    usable: List[Tuple[Dict, str, float]] = []

    for filing in org_json.get("filings_with_data") or []:
        label = form_label(filing.get("formtype"))
        if label == FORM_990PF:
            report.skipped_pf += 1
            continue
        receipts = gross_receipts(filing)
        if label is None or receipts is None or filing.get("tax_prd") is None:
            report.skipped_missing_data += 1
            continue
        period = int(filing["tax_prd"])
        receipts_by_period[period] = receipts
        usable.append((filing, label, receipts))

    usable.sort(key=lambda item: int(item[0]["tax_prd"]), reverse=True)

    for filing, label, receipts in usable:
        period = int(filing["tax_prd"])
        history = [receipts]
        cursor = period
        for _ in range(2):
            cursor = previous_period(cursor)
            if cursor not in receipts_by_period:
                break
            history.append(receipts_by_period[cursor])
        total_revenue = filing.get("totrevenue")
        if label == FORM_990EZ and filing.get("totrevnue") is not None:
            total_revenue = filing.get("totrevnue")
        assets = filing.get("totassetsend")
        report.records.append(
            FilingRecord(
                ein=int(filing.get("ein") or org.get("ein") or 0),
                name=str(org.get("name") or ""),
                tax_prd=period,
                tax_year=int(filing.get("tax_prd_yr") or period // 100),
                form_filed=label,
                total_revenue=_num(total_revenue),
                gross_receipts=receipts,
                total_assets_end=None if assets is None else float(assets),
                age_years=age_years_at(org.get("ruling_date"), period),
                ruling_date=org.get("ruling_date"),
                subsection_code=org.get("subsection_code"),
                filing_requirement_code=org.get("filing_requirement_code"),
                history=tuple(history),
                history_complete=len(history) == 3,
            )
        )
    return report


# ---- Prediction normalization ---------------------------------------------------


_REVIEW_PATTERN = re.compile(r"\b(REVIEW|HOLD|HELD)\b")
_VARIANT_KEYS = ("variant", "form_variant", "form", "form_type", "routed_form", "routed_form_variant", "result")
_REVIEW_KEYS = ("requires_review", "needs_review", "review_required", "hold_for_review", "preparer_review", "review", "hold", "held")
_REASON_KEYS = ("reason", "reasons", "explanation", "note", "notes", "detail", "message")
_REVIEW_REASON_KEYS = ("review_reasons", "review_reason", "review_notes", "hold_reasons", "hold_reason")
_TRUE_WORDS = {"true", "yes", "y", "required", "hold", "held", "review"}
_FALSE_WORDS = {"false", "no", "n", "none", "not required", "not_required", "no review", ""}


def parse_variant(text: Any) -> Optional[str]:
    if text is None:
        return None
    if hasattr(text, "value") and not isinstance(text, (str, bytes)):
        text = text.value
    s = str(text).upper().replace("_", "-").replace(" ", "-")
    if "EZ" in s:
        return FORM_990EZ
    if re.search(r"990-?N\b", s) or s in ("N", "E-POSTCARD", "EPOSTCARD"):
        return FORM_990N
    if "FULL" in s or "990" in s:
        return FORM_990
    return None


def review_flag(value: Any) -> Optional[bool]:
    """Read a review indicator strictly. Returns None when the value is not a flag.

    A bare object or a bound method is never treated as True: that is how a
    correct routing decision can be mis-scored as held for review.
    """
    if value is None or callable(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, Enum):
        return review_flag(value.value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE_WORDS:
            return True
        if text in _FALSE_WORDS:
            return False
        return None
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0  # a non-empty list of review reasons means held
    for attr in ("required", "needed", "flagged", "value"):
        inner = getattr(value, attr, None)
        if isinstance(inner, bool):
            return inner
    return None


def _join_reasons(*values: Any) -> Optional[str]:
    parts = []
    for value in values:
        if not value:
            continue
        if isinstance(value, (list, tuple, set)):
            parts.extend(str(v) for v in value if v)
        else:
            parts.append(str(value))
    return " | ".join(parts) if parts else None


def normalize_prediction(result: Any) -> Prediction:
    """Accept whatever route_form_variant returns and reduce it to a Prediction."""
    if isinstance(result, Prediction):
        return result
    if result is None:
        return Prediction(variant=None, review=False, reason="router returned None")

    if isinstance(result, dict):
        get = result.get
    elif isinstance(result, (str, bytes, Enum)):
        s = str(result.value if isinstance(result, Enum) else result).upper()
        return Prediction(variant=parse_variant(s), review=bool(_REVIEW_PATTERN.search(s)), reason=None)
    else:
        def get(key, default=None):  # object with attributes
            return getattr(result, key, default)

    variant = None
    for key in _VARIANT_KEYS:
        value = get(key)
        if value is not None and not callable(value):
            variant = parse_variant(value)
            if variant is not None or isinstance(value, str):
                break

    review = None
    for key in _REVIEW_KEYS:
        flag = review_flag(get(key))
        if flag is not None:
            review = flag
            break
    if review is None:
        review = any(
            isinstance(get(key), str) and _REVIEW_PATTERN.search(get(key).upper()) for key in _VARIANT_KEYS
        )

    decision_reason = next((get(key) for key in _REASON_KEYS if get(key) and not callable(get(key))), None)
    review_reason = next((get(key) for key in _REVIEW_REASON_KEYS if get(key) and not callable(get(key))), None)
    return Prediction(variant=variant, review=bool(review), reason=_join_reasons(decision_reason, review_reason))


# ---- Router adapter -----------------------------------------------------------------

_CURRENT = lambda r: r.gross_receipts  # noqa: E731
_ASSETS = lambda r: r.total_assets_end  # noqa: E731
_AGE = lambda r: r.age_years  # noqa: E731
_FULL_HISTORY = lambda r: tuple(r.history)  # noqa: E731  (current year first, then up to two priors)
_PRIOR_YEARS = lambda r: tuple(r.history[1:])  # noqa: E731  (priors only; current year is passed separately)

# Router parameters that configure the rule rather than describe the record. These are
# left at the router's own defaults on purpose and are not reported as unbound.
CONFIGURATION_PARAMETERS = frozenset({
    "review_band", "review_margin", "margin", "tolerance", "band", "boundary_margin", "threshold_margin", "hold_band",
})

_PARAMETER_ALIASES: Dict[str, Callable[[FilingRecord], Any]] = {
    # current-year gross receipts
    "gross_receipts": _CURRENT,
    "receipts": _CURRENT,
    "current_gross_receipts": _CURRENT,
    "gross_receipts_current": _CURRENT,
    # total assets, end of year
    "total_assets": _ASSETS,
    "assets": _ASSETS,
    "total_assets_end": _ASSETS,
    "total_assets_eoy": _ASSETS,
    # organization age in years at fiscal year end
    "age": _AGE,
    "age_years": _AGE,
    "age_in_years": _AGE,
    "org_age_years": _AGE,
    "organization_age": _AGE,
    "organization_age_years": _AGE,
    "years_in_existence": _AGE,
    "years_since_ruling": _AGE,
    # full history including the current year
    "history": _FULL_HISTORY,
    "gross_receipts_history": _FULL_HISTORY,
    "receipts_history": _FULL_HISTORY,
    # prior years only (the router receives the current year as gross_receipts)
    "prior_year_gross_receipts": _PRIOR_YEARS,
    "prior_years_gross_receipts": _PRIOR_YEARS,
    "prior_gross_receipts": _PRIOR_YEARS,
    "prior_year_receipts": _PRIOR_YEARS,
    "prior_receipts": _PRIOR_YEARS,
    "prior_years": _PRIOR_YEARS,
    "previous_gross_receipts": _PRIOR_YEARS,
    "tax_year": lambda r: r.tax_year,
}


def make_router_adapter(route_fn: Callable[..., Any]) -> Callable[[FilingRecord], Prediction]:
    """Bind the router's actual parameter names to harness inputs by name.

    A required parameter the harness cannot supply raises a TypeError naming
    it. A defaulted parameter the harness cannot supply is listed on the
    returned function as ``unbound_parameters``; callers print it, because a
    silently omitted parameter (age, prior years) makes the router hold every
    record for review and the harness reports nothing decided. Defaulted
    parameters that configure the rule (``review_band`` and the like, see
    CONFIGURATION_PARAMETERS) are listed separately as
    ``configuration_parameters`` and are meant to stay at their defaults.
    """
    signature = inspect.signature(route_fn)
    bound_names: List[str] = []
    unbound: List[str] = []
    configuration: List[str] = []
    missing: List[str] = []
    for name, parameter in signature.parameters.items():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if name in _PARAMETER_ALIASES:
            bound_names.append(name)
        elif parameter.default is inspect.Parameter.empty:
            missing.append(name)
        elif name in CONFIGURATION_PARAMETERS:
            configuration.append(name)
        else:
            unbound.append(name)
    if missing:
        raise TypeError(
            f"router requires parameters the harness cannot supply: {missing}; "
            f"signature is {route_fn.__name__}{signature}. Add an alias in _PARAMETER_ALIASES."
        )

    def router(record: FilingRecord) -> Prediction:
        kwargs = {name: _PARAMETER_ALIASES[name](record) for name in bound_names}
        return normalize_prediction(route_fn(**kwargs))

    router.bound_parameters = tuple(bound_names)  # type: ignore[attr-defined]
    router.unbound_parameters = tuple(unbound)  # type: ignore[attr-defined]
    router.configuration_parameters = tuple(configuration)  # type: ignore[attr-defined]  (left at router defaults)
    router.signature = str(signature)  # type: ignore[attr-defined]
    return router


def reference_router(record: FilingRecord) -> Prediction:
    """The plain form tests, with no age tiers and no averaging.

    Used to check the harness itself and as a floor for the project router:
    990 if gross receipts >= $200,000 or total assets >= $500,000; otherwise
    990-N if gross receipts <= $50,000; otherwise 990-EZ.
    """
    assets = record.total_assets_end or 0.0
    if record.gross_receipts >= EZ_GROSS_RECEIPTS_LIMIT or assets >= EZ_TOTAL_ASSETS_LIMIT:
        return Prediction(FORM_990)
    if record.gross_receipts <= N_ESTABLISHED_LIMIT:
        return Prediction(FORM_990N)
    return Prediction(FORM_990EZ)


# ---- Classification --------------------------------------------------------------


def near_boundary(record: FilingRecord, margin: float = BOUNDARY_MARGIN) -> Tuple[str, ...]:
    flags = []
    if abs(record.gross_receipts - EZ_GROSS_RECEIPTS_LIMIT) <= EZ_GROSS_RECEIPTS_LIMIT * margin:
        flags.append("ez_receipts")
    if record.total_assets_end is not None and abs(record.total_assets_end - EZ_TOTAL_ASSETS_LIMIT) <= EZ_TOTAL_ASSETS_LIMIT * margin:
        flags.append("ez_assets")
    if abs(record.gross_receipts - N_ESTABLISHED_LIMIT) <= N_ESTABLISHED_LIMIT * margin:
        flags.append("n_receipts")
    return tuple(flags)


def filer_eligible_for_ez(record: FilingRecord) -> bool:
    """Form 990-EZ item L applied to the filer's own figures."""
    assets = record.total_assets_end or 0.0
    return record.gross_receipts < EZ_GROSS_RECEIPTS_LIMIT and assets < EZ_TOTAL_ASSETS_LIMIT


def classify(prediction: Prediction, record: FilingRecord) -> Tuple[str, Optional[str]]:
    if prediction.review:
        return REVIEW, None
    if prediction.variant not in RANK:
        return NO_PREDICTION, None
    predicted, actual = prediction.variant, record.form_filed
    if predicted == actual:
        return MATCH, None
    if RANK[predicted] < RANK[actual]:
        attribution = N_ELIGIBLE_FILED_FULLER_FORM if predicted == FORM_990N else EZ_ELIGIBLE_FILED_FULL_990
        return PERMITTED_UPGRADE, attribution
    # predicted a fuller form than was filed
    if actual == FORM_990EZ and not filer_eligible_for_ez(record):
        return UNDER_FILED, FILER_INELIGIBLE_BY_OWN_FIGURES
    return UNDER_FILED, ROUTER_DISAGREES_WITH_FORM_TEST


def evaluate_records(records: Iterable[FilingRecord], router: Callable[[FilingRecord], Prediction]) -> List[EvaluationResult]:
    results = []
    for record in records:
        prediction = router(record)
        outcome, attribution = classify(prediction, record)
        results.append(EvaluationResult(record, prediction, outcome, attribution, near_boundary(record)))
    return results


def evaluate_organization(org_json: Dict, router: Callable[[FilingRecord], Prediction]) -> List[EvaluationResult]:
    return evaluate_records(build_records(org_json).records, router)


LIMITATIONS = (
    "990-N: ProPublica excludes e-Postcard filers, so no filing in this data set is labeled 990-N. "
    "A 990-N prediction can only be scored as a permitted upgrade; the $50,000 tier is not validated by this harness.",
    "Age is measured from the IRS ruling date, a lower bound on the organization's age.",
)


# ---- Summary ----------------------------------------------------------------------------


def summarize(results: Sequence[EvaluationResult]) -> Dict[str, Any]:
    outcomes: Dict[str, int] = {}
    attributions: Dict[str, int] = {}
    confusion: Dict[str, Dict[str, int]] = {}
    boundary: Dict[str, Dict[str, int]] = {}
    orgs = set()
    history_complete = 0
    age_under_three = 0
    age_unknown = 0

    for result in results:
        outcomes[result.outcome] = outcomes.get(result.outcome, 0) + 1
        if result.attribution:
            attributions[result.attribution] = attributions.get(result.attribution, 0) + 1
        predicted = "review" if result.prediction.review else (result.prediction.variant or "none")
        confusion.setdefault(result.record.form_filed, {})
        confusion[result.record.form_filed][predicted] = confusion[result.record.form_filed].get(predicted, 0) + 1
        for flag in result.near_boundary:
            boundary.setdefault(flag, {})
            boundary[flag][result.outcome] = boundary[flag].get(result.outcome, 0) + 1
        orgs.add(result.record.ein)
        history_complete += int(result.record.history_complete)
        if result.record.age_years is None:
            age_unknown += 1
        elif result.record.age_years < 3:
            age_under_three += 1

    decided = outcomes.get(MATCH, 0) + outcomes.get(PERMITTED_UPGRADE, 0) + outcomes.get(UNDER_FILED, 0)
    strict = outcomes.get(MATCH, 0) / decided if decided else None
    lenient = (outcomes.get(MATCH, 0) + outcomes.get(PERMITTED_UPGRADE, 0)) / decided if decided else None

    return {
        "filings": len(results),
        "organizations": len(orgs),
        "outcomes": outcomes,
        "attributions": attributions,
        "decided": decided,
        "strict_accuracy": strict,
        "lenient_accuracy": lenient,
        "confusion_actual_vs_predicted": confusion,
        "near_boundary": boundary,
        "history_complete": history_complete,
        "age_under_three_years_by_ruling_date": age_under_three,
        "age_unknown": age_unknown,
        "labels_present": sorted(confusion.keys()),
        "limitations": list(LIMITATIONS),
    }


# ---- Sampling across the size range ---------------------------------------------

DEFAULT_BANDS: Tuple[Tuple[str, float, Optional[float]], ...] = (
    ("under_50k", 0, 50_000),
    ("50k_to_200k", 50_000, 200_000),
    ("200k_to_500k", 200_000, 500_000),
    ("500k_plus", 500_000, None),
)


def size_band(amount: Optional[float], bands=DEFAULT_BANDS) -> Optional[str]:
    if amount is None:
        return None
    for name, low, high in bands:
        if amount >= low and (high is None or amount < high):
            return name
    return None


class BandFiller:
    """Accept organizations until every band holds ``target`` of them."""

    def __init__(self, target: int, bands=DEFAULT_BANDS) -> None:
        self.target = target
        self.bands = bands
        self.counts: Dict[str, int] = {name: 0 for name, _, _ in bands}

    def has_room(self, amount: Optional[float]) -> bool:
        band = size_band(amount, self.bands)
        return band is not None and self.counts[band] < self.target

    def accept(self, amount: Optional[float]) -> bool:
        if not self.has_room(amount):
            return False
        self.counts[size_band(amount, self.bands)] += 1
        return True

    def is_full(self) -> bool:
        return all(count >= self.target for count in self.counts.values())
