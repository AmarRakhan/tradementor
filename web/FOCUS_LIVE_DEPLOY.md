# Strategy 2 Focus Live

Deployment marker and operator note for the shared V45 test application.

Focus Live uses the same planner as Focus Shadow, but real exchange execution remains explicitly user-enabled. The live cycle is: select one LONG pair, open, manage DCA and optional partial exits, trail the remaining position, close the cycle, then rescan and select/re-enter for the next cycle when the configured risk and budget gates allow it.

Manual pair selection is exposed as a scrollable current-market list rather than requiring the symbol to be typed.

Safety invariants remain in force: normal Multi-pair seat filling is suppressed while Focus is selected; pre-existing Strategy-2 positions continue to be managed; Focus cannot exceed the account-wide 15 exchange-order actions per scan; Shadow sends zero orders; and enabling Focus Live requires explicit live confirmation.
