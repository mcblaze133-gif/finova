# Preparing company evidence

The configured source folder is read only to SignalAI. Put PDFs and CSVs in company subfolders, for example `hul/annual-reports/`, `hul/results/`, `hul/earnings-calls/`, and `hul/financials.csv`. Do the same for peers. The folder currently needs to be populated by you.

Preserve the original downloaded PDFs. Record their original URLs and publication dates. A filename or a model's recollection does not establish the reporting period or source provenance.

Use the adjacent header-only CSV template for normalized financial records. Enter amounts as unformatted decimal numbers. Units are `INR`, `INR_lakh`, `INR_crore`, `shares`, `fraction`, `ratio` or `multiple`. Source paths are relative to the configured source folder. All source-file references must exist inside that folder.

Source categories stay distinct: `historical`, `external`, `management_guidance`, `analyst_assumption`. Historical financials require `user_verified` (your review assertion), or internal `source_verified` review with a matching file hash, exact page evidence and review notes. Neither importing a PDF nor importing an ordinary CSV automatically verifies financial figures. SignalAI source review is recorded separately and never labelled as user verification.

Use one accounting basis and one operations scope per company export. Do not combine standalone and consolidated facts. Annual flow records require period_start and period_end; balance-sheet stocks use the actual observation date. Stub periods and 18-month financial years need reconciliation before annual forecasts.

Source fields required: source_url, source_file, source_page, source_date, definition. Use the actual PDF page or CSV row reference. Never fill missing financial fields with zero. Enter zero only where the original evidence establishes it.

Supported historical metric IDs: revenue, ebitda, da, ebit, net_income (attributable to ordinary shareholders), cfo, capex, operating_nwc, debt, cash (non-operating cash eligible for the equity bridge), nci, preferred, nonoperating_assets, book_equity, shares, dividends, interest, assets, liabilities, invested_capital.

Market inputs, peer observations, transaction terms and segment values must be dated and normalized independently. Acquisition consideration is not automatically enterprise value. A partial stake price does not establish 100% value without a documented basis.
