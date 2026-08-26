"""The fixed line inventories of Form 990, held as data.

These lists do not vary by organization. They are printed on the form. The
model should never be asked to recall them, and when it is, it invents:
across successive runs against the same company it produced references to
Schedules S, T, U ... through AK and AP, none of which exist. The Form 990
schedules end at R.

The cause is in the prompt, which instructs the model to "answer lines 1-38
Yes/No from derivable facts" while supplying a template containing a single
example row. The model knows it owes thirty-eight lines and does not know
what they are, so it continues the alphabet.

Text below is taken from the 2025 Form 990 (Rev. 4/30/25), trimmed of dot
leaders and field numbering. Where a line has sub-parts they are listed
individually, because each carries its own answer box.

Source: https://www.irs.gov/pub/irs-pdf/f990.pdf
"""

from __future__ import annotations

__all__ = [
    "VALID_SCHEDULES",
    "PART_IV_CHECKLIST",
    "PART_V_LINES",
    "PART_VI_SECTION_A",
    "PART_VI_SECTION_B",
    "PART_VI_SECTION_C",
    "PART_IX_LINES",
    "part_iv_line_numbers",
]

# Form 990 schedules run A to R. Nothing beyond R exists.
VALID_SCHEDULES = frozenset("ABCDEFGHIJKLMNOPQR")


# --- Part IV, Checklist of Required Schedules ---------------------------
# (line, schedule triggered or None, question)
PART_IV_CHECKLIST: tuple[tuple[str, str | None, str], ...] = (
    ("1", "A", "Is the organization described in section 501(c)(3) or 4947(a)(1) (other than a private foundation)?"),
    ("2", "B", "Is the organization required to complete Schedule B, Schedule of Contributors?"),
    ("3", "C", "Did the organization engage in direct or indirect political campaign activities on behalf of or in opposition to candidates for public office?"),
    ("4", "C", "Section 501(c)(3) organizations. Did the organization engage in lobbying activities, or have a section 501(h) election in effect during the tax year?"),
    ("5", "C", "Is the organization a section 501(c)(4), 501(c)(5), or 501(c)(6) organization that receives membership dues, assessments, or similar amounts as defined in Rev. Proc. 98-19?"),
    ("6", "D", "Did the organization maintain any donor advised funds or any similar funds or accounts for which donors have the right to provide advice on the distribution or investment of amounts in such funds or accounts?"),
    ("7", "D", "Did the organization receive or hold a conservation easement, including easements to preserve open space, the environment, historic land areas, or historic structures?"),
    ("8", "D", "Did the organization maintain collections of works of art, historical treasures, or other similar assets?"),
    ("9", "D", "Did the organization report an amount in Part X, line 21, for escrow or custodial account liability; serve as a custodian for amounts not listed in Part X; or provide credit counseling, debt management, credit repair, or debt negotiation services?"),
    ("10", "D", "Did the organization, directly or through a related organization, hold assets in donor-restricted endowments or in quasi-endowments?"),
    ("11a", "D", "Did the organization report an amount for land, buildings, and equipment in Part X, line 10?"),
    ("11b", "D", "Did the organization report an amount for investments-other securities in Part X, line 12, that is 5% or more of its total assets reported in Part X, line 16?"),
    ("11c", "D", "Did the organization report an amount for investments-program related in Part X, line 13, that is 5% or more of its total assets reported in Part X, line 16?"),
    ("11d", "D", "Did the organization report an amount for other assets in Part X, line 15, that is 5% or more of its total assets reported in Part X, line 16?"),
    ("11e", "D", "Did the organization report an amount for other liabilities in Part X, line 25?"),
    ("11f", "D", "Did the organization's separate or consolidated financial statements for the tax year include a footnote that addresses the organization's liability for uncertain tax positions under FIN 48 (ASC 740)?"),
    ("12a", "D", "Did the organization obtain separate, independent audited financial statements for the tax year?"),
    ("12b", "D", "Was the organization included in consolidated, independent audited financial statements for the tax year?"),
    ("13", "E", "Is the organization a school described in section 170(b)(1)(A)(ii)?"),
    ("14a", None, "Did the organization maintain an office, employees, or agents outside of the United States?"),
    ("14b", "F", "Did the organization have aggregate revenues or expenses of more than $10,000 from grantmaking, fundraising, business, investment, and program service activities outside the United States, or aggregate foreign investments valued at $100,000 or more?"),
    ("15", "F", "Did the organization report on Part IX, column (A), line 3, more than $5,000 of grants or other assistance to or for any foreign organization?"),
    ("16", "F", "Did the organization report on Part IX, column (A), line 3, more than $5,000 of aggregate grants or other assistance to or for foreign individuals?"),
    ("17", "G", "Did the organization report a total of more than $15,000 of expenses for professional fundraising services on Part IX, column (A), lines 6 and 11e?"),
    ("18", "G", "Did the organization report more than $15,000 total of fundraising event gross income and contributions on Part VIII, lines 1c and 8a?"),
    ("19", "G", "Did the organization report more than $15,000 of gross income from gaming activities on Part VIII, line 9a?"),
    ("20a", "H", "Did the organization operate one or more hospital facilities?"),
    ("20b", "H", "If 'Yes' to line 20a, did the organization attach a copy of its audited financial statements to this return?"),
    ("21", "I", "Did the organization report more than $5,000 of grants or other assistance to any domestic organization or domestic government on Part IX, column (A), line 1?"),
    ("22", "I", "Did the organization report more than $5,000 of grants or other assistance to or for domestic individuals on Part IX, column (A), line 2?"),
    ("23", "J", "Did the organization answer 'Yes' to Part VII, Section A, line 3, 4, or 5, about compensation of the organization's current and former officers, directors, trustees, key employees, and highest compensated employees?"),
    ("24a", "K", "Did the organization have a tax-exempt bond issue with an outstanding principal amount of more than $100,000 as of the last day of the year, that was issued after December 31, 2002?"),
    ("24b", "K", "Did the organization invest any proceeds of tax-exempt bonds beyond a temporary period exception?"),
    ("24c", "K", "Did the organization maintain an escrow account other than a refunding escrow at any time during the year to defease any tax-exempt bonds?"),
    ("24d", "K", "Did the organization act as an 'on behalf of' issuer for bonds outstanding at any time during the year?"),
    ("25a", "L", "Section 501(c)(3), 501(c)(4), and 501(c)(29) organizations. Did the organization engage in an excess benefit transaction with a disqualified person during the year?"),
    ("25b", "L", "Is the organization aware that it engaged in an excess benefit transaction with a disqualified person in a prior year, and that the transaction has not been reported on any of the organization's prior Forms 990 or 990-EZ?"),
    ("26", "L", "Did the organization report any amount on Part X, line 5 or 22, for receivables from or payables to any current or former officer, director, trustee, key employee, creator or founder, substantial contributor, or 35% controlled entity or family member of any of these persons?"),
    ("27", "L", "Did the organization provide a grant or other assistance to any current or former officer, director, trustee, key employee, creator or founder, substantial contributor or employee thereof, a grant selection committee member, or to a 35% controlled entity or family member of any of these persons?"),
    ("28a", "L", "Was the organization a party to a business transaction with a current or former officer, director, trustee, key employee, creator or founder, or substantial contributor?"),
    ("28b", "L", "Was the organization a party to a business transaction with a family member of any individual described in line 28a?"),
    ("28c", "L", "Was the organization a party to a business transaction with a 35% controlled entity of one or more individuals and/or organizations described in line 28a or 28b?"),
    ("29", "M", "Did the organization receive more than $25,000 in noncash contributions?"),
    ("30", "M", "Did the organization receive contributions of art, historical treasures, or other similar assets, or qualified conservation contributions?"),
    ("31", "N", "Did the organization liquidate, terminate, or dissolve and cease operations?"),
    ("32", "N", "Did the organization sell, exchange, dispose of, or transfer more than 25% of its net assets?"),
    ("33", "R", "Did the organization own 100% of an entity disregarded as separate from the organization under Regulations sections 301.7701-2 and 301.7701-3?"),
    ("34", "R", "Was the organization related to any tax-exempt or taxable entity?"),
    ("35a", None, "Did the organization have a controlled entity within the meaning of section 512(b)(13)?"),
    ("35b", "R", "If 'Yes' to line 35a, did the organization receive any payment from or engage in any transaction with a controlled entity within the meaning of section 512(b)(13)?"),
    ("36", "R", "Section 501(c)(3) organizations. Did the organization make any transfers to an exempt non-charitable related organization?"),
    ("37", "R", "Did the organization conduct more than 5% of its activities through an entity that is not a related organization and that is treated as a partnership for federal income tax purposes?"),
    ("38", "O", "Did the organization complete Schedule O and provide explanations on Schedule O for Part VI, lines 11b and 19? Note: All Form 990 filers are required to complete Schedule O."),
)


# --- Part V, Statements Regarding Other IRS Filings and Tax Compliance ---
PART_V_LINES: tuple[tuple[str, str], ...] = (
    ("1a", "Enter the number reported in box 3 of Form 1096."),
    ("1b", "Enter the number of Forms W-2G included on line 1a."),
    ("1c", "Did the organization comply with backup withholding rules for reportable payments to vendors and reportable gaming winnings to prize winners?"),
    ("2a", "Enter the number of employees reported on Form W-3 filed for the calendar year ending with or within the year covered by this return."),
    ("2b", "If at least one is reported on line 2a, did the organization file all required federal employment tax returns?"),
    ("3a", "Did the organization have unrelated business gross income of $1,000 or more during the year?"),
    ("3b", "If 'Yes,' has it filed a Form 990-T for this year?"),
    ("4a", "At any time during the calendar year, did the organization have an interest in, or a signature or other authority over, a financial account in a foreign country?"),
    ("4b", "If 'Yes,' enter the name of the foreign country."),
    ("5a", "Was the organization a party to a prohibited tax shelter transaction at any time during the tax year?"),
    ("5b", "Did any taxable party notify the organization that it was or is a party to a prohibited tax shelter transaction?"),
    ("5c", "If 'Yes' to line 5a or 5b, did the organization file Form 8886-T?"),
    ("6a", "Does the organization have annual gross receipts that are normally greater than $100,000, and did the organization solicit any contributions that were not tax deductible as charitable contributions?"),
    ("6b", "If 'Yes,' did the organization include with every solicitation an express statement that such contributions or gifts were not tax deductible?"),
    ("7a", "Did the organization receive a payment in excess of $75 made partly as a contribution and partly for goods and services provided to the payor?"),
    ("7b", "If 'Yes,' did the organization notify the donor of the value of the goods or services provided?"),
    ("7c", "Did the organization sell, exchange, or otherwise dispose of tangible personal property for which it was required to file Form 8282?"),
    ("7d", "If 'Yes,' indicate the number of Forms 8282 filed during the year."),
    ("7e", "Did the organization receive any funds, directly or indirectly, to pay premiums on a personal benefit contract?"),
    ("7f", "Did the organization, during the year, pay premiums, directly or indirectly, on a personal benefit contract?"),
    ("7g", "If the organization received a contribution of qualified intellectual property, did the organization file Form 8899 as required?"),
    ("7h", "If the organization received a contribution of cars, boats, airplanes, or other vehicles, did the organization file a Form 1098-C?"),
    ("8", "Sponsoring organizations maintaining donor advised funds. Did a donor advised fund maintained by the sponsoring organization have excess business holdings at any time during the year?"),
    ("9a", "Did the sponsoring organization make any taxable distributions under section 4966?"),
    ("9b", "Did the sponsoring organization make a distribution to a donor, donor advisor, or related person?"),
    ("10a", "Section 501(c)(7) organizations. Initiation fees and capital contributions included on Part VIII, line 12."),
    ("10b", "Section 501(c)(7) organizations. Gross receipts, included on Form 990, Part VIII, line 12, for public use of club facilities."),
    ("11a", "Section 501(c)(12) organizations. Gross income from members or shareholders."),
    ("11b", "Section 501(c)(12) organizations. Gross income from other sources."),
    ("12a", "Section 4947(a)(1) non-exempt charitable trusts. Is the organization filing Form 990 in lieu of Form 1041?"),
    ("12b", "If 'Yes,' enter the amount of tax-exempt interest received or accrued during the year."),
    ("13a", "Section 501(c)(29) qualified nonprofit health insurance issuers. Is the organization licensed to issue qualified health plans in more than one state?"),
    ("13b", "Enter the amount of reserves the organization is required to maintain by the states in which the organization is licensed to issue qualified health plans."),
    ("13c", "Enter the amount of reserves on hand."),
    ("14a", "Did the organization receive any payments for indoor tanning services during the tax year?"),
    ("14b", "If 'Yes,' has it filed a Form 720 to report these payments?"),
    ("15", "Is the organization subject to the section 4960 tax on payment(s) of more than $1,000,000 in remuneration or excess parachute payment(s) during the year?"),
    ("16", "Is the organization an educational institution subject to the section 4968 excise tax on net investment income?"),
    ("17", "Section 501(c)(21) organizations. Did the trust, or any disqualified or other person, engage in any activities that would result in the imposition of an excise tax under section 4951, 4952, or 4953?"),
)


# --- Part VI, Governance, Management, and Disclosure ---------------------
PART_VI_SECTION_A: tuple[tuple[str, str], ...] = (
    ("1a", "Enter the number of voting members of the governing body at the end of the tax year."),
    ("1b", "Enter the number of voting members included on line 1a who are independent."),
    ("2", "Did any officer, director, trustee, or key employee have a family relationship or a business relationship with any other officer, director, trustee, or key employee?"),
    ("3", "Did the organization delegate control over management duties customarily performed by or under the direct supervision of officers, directors, trustees, or key employees to a management company or other person?"),
    ("4", "Did the organization make any significant changes to its governing documents since the prior Form 990 was filed?"),
    ("5", "Did the organization become aware during the year of a significant diversion of the organization's assets?"),
    ("6", "Did the organization have members or stockholders?"),
    ("7a", "Did the organization have members, stockholders, or other persons who had the power to elect or appoint one or more members of the governing body?"),
    ("7b", "Are any governance decisions of the organization reserved to (or subject to approval by) members, stockholders, or persons other than the governing body?"),
    ("8a", "Did the organization contemporaneously document the meetings held or written actions undertaken during the year by the governing body?"),
    ("8b", "Did the organization contemporaneously document the meetings held or written actions undertaken during the year by each committee with authority to act on behalf of the governing body?"),
    ("9", "Is there any officer, director, trustee, or key employee listed in Part VII, Section A, who cannot be reached at the organization's mailing address?"),
)

PART_VI_SECTION_B: tuple[tuple[str, str], ...] = (
    ("10a", "Did the organization have local chapters, branches, or affiliates?"),
    ("10b", "If 'Yes,' did the organization have written policies and procedures governing the activities of such chapters, affiliates, and branches?"),
    ("11a", "Has the organization provided a complete copy of this Form 990 to all members of its governing body before filing the form?"),
    ("12a", "Did the organization have a written conflict of interest policy?"),
    ("12b", "Were officers, directors, or trustees, and key employees required to disclose annually interests that could give rise to conflicts?"),
    ("12c", "Did the organization regularly and consistently monitor and enforce compliance with the policy?"),
    ("13", "Did the organization have a written whistleblower policy?"),
    ("14", "Did the organization have a written document retention and destruction policy?"),
    ("15a", "Did the process for determining compensation of the organization's CEO, Executive Director, or top management official include a review and approval by independent persons, comparability data, and contemporaneous substantiation?"),
    ("15b", "Did the process for determining compensation of other officers or key employees include a review and approval by independent persons, comparability data, and contemporaneous substantiation?"),
    ("16a", "Did the organization invest in, contribute assets to, or participate in a joint venture or similar arrangement with a taxable entity during the year?"),
    ("16b", "If 'Yes,' did the organization follow a written policy or procedure requiring the organization to evaluate its participation in joint venture arrangements under applicable federal tax law?"),
)

PART_VI_SECTION_C: tuple[tuple[str, str], ...] = (
    ("17", "List the states with which a copy of this Form 990 is required to be filed."),
    ("18", "Indicate how the organization made its Forms 1023, 990, and 990-T available for public inspection."),
    ("19", "Describe whether (and if so, how) the organization made its governing documents, conflict of interest policy, and financial statements available to the public during the tax year."),
    ("20", "State the name, address, and telephone number of the person who possesses the organization's books and records."),
)


# --- Part IX, Statement of Functional Expenses --------------------------
PART_IX_LINES: tuple[tuple[str, str], ...] = (
    ("1", "Grants and other assistance to domestic organizations and domestic governments"),
    ("2", "Grants and other assistance to domestic individuals"),
    ("3", "Grants and other assistance to foreign organizations, foreign governments, and foreign individuals"),
    ("4", "Benefits paid to or for members"),
    ("5", "Compensation of current officers, directors, trustees, and key employees"),
    ("6", "Compensation not included above to disqualified persons"),
    ("7", "Other salaries and wages"),
    ("8", "Pension plan accruals and contributions"),
    ("9", "Other employee benefits"),
    ("10", "Payroll taxes"),
    ("11a", "Fees for services (nonemployees): Management"),
    ("11b", "Fees for services (nonemployees): Legal"),
    ("11c", "Fees for services (nonemployees): Accounting"),
    ("11d", "Fees for services (nonemployees): Lobbying"),
    ("11e", "Fees for services (nonemployees): Professional fundraising services"),
    ("11f", "Fees for services (nonemployees): Investment management fees"),
    ("11g", "Fees for services (nonemployees): Other"),
    ("12", "Advertising and promotion"),
    ("13", "Office expenses"),
    ("14", "Information technology"),
    ("15", "Royalties"),
    ("16", "Occupancy"),
    ("17", "Travel"),
    ("18", "Payments of travel or entertainment expenses for any federal, state, or local public officials"),
    ("19", "Conferences, conventions, and meetings"),
    ("20", "Interest"),
    ("21", "Payments to affiliates"),
    ("22", "Depreciation, depletion, and amortization"),
    ("23", "Insurance"),
    ("24e", "All other expenses"),
    ("25", "Total functional expenses"),
)


def part_iv_line_numbers() -> tuple[str, ...]:
    """Every answer box on Part IV, sub-lines included."""
    return tuple(line for line, _, _ in PART_IV_CHECKLIST)
