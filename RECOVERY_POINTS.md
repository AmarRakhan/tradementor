# Recovery Points

## recovery-2026-08-25-pre-strategy2-performance

- Datum: 25 augustus 2026
- Omschrijving: Werkende productie vóór Strategy-2 performance-optimalisatie.
- Commit SHA: d8683ffce61b8d484373b58477cf57056fa0eba2
- Live Cloud Run revision: tradementor-api-gh-d8683ffc-1
- Branch: amar-crypto-bot-2026-cloud
- Cloud project: tradementor-production
- Service: tradementor-api
- Scheduler: tradementor-aster-automation	ENABLED	* * * * *	Etc/UTC	https://tradementor-api-604335232956.europe-west4.run.app/internal/aster-automation/tick
- Opmerking: Dit recovery point is gemaakt vóór optimalisatie van Strategy-2 scheduler, Firestore audit reads en runtime performance. Tradingfunctionaliteit werkte op dit punt volgens de bestaande productieversie.
