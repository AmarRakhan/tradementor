# GitHub-koppelingscommando's

Gebruik deze volgorde op je eigen pc in `C:\HyperEdge\Android\TradeMentor`.

## 1) GitHub-repo maken
- Maak op GitHub een lege repo aan: `tradementor` (publiek of privé)

## 2) Lokaal koppelen

```powershell
git config --global --add safe.directory C:/HyperEdge/Android/TradeMentor
git remote add origin https://github.com/<jouw-gebruikersnaam>/tradementor.git
git checkout -b main
```

> Als je met je eigen Windows-gebruiker werkt kan "dubious ownership" verschijnen; bovenstaande safe.directory-regel voorkomt dat.

## 3) Eerste baseline commit (geen lokale runtime-data)

```powershell
git add README.md docs .github app build.gradle.kts settings.gradle.kts gradle* gradlew* gradle.properties cloud trading_server
git commit -m "chore: baseline trade mentor cloud-first setup"
git push -u origin main
```

### Als er veel oude debug-bestanden zijn

```powershell
git rm -r --cached .android .android-signing-home .android-user-home .gradle-user .gradle-user-home .codex-tools .tmp* 2>$null
git add README.md docs .github app build.gradle.kts settings.gradle.kts gradle* gradlew* gradle.properties cloud trading_server
git commit -m "chore: clean git history before cloud push"
```

## 4) Test/public branch structuur

Gebruik deze lokale structuur:
- `main` = publieke stabiele versie
- `test` = interne testversie

```powershell
git checkout -b test
git push -u origin test
```

Uit test naar main:

```powershell
git checkout main
git merge --no-ff test -m "chore: release from test"
git push origin main
```

## 5) Veiligheid check

```powershell
git status --ignored
```

Als iets per ongeluk zichtbaar blijft in `git status`, voeg dan toe aan `.gitignore` en commit opnieuw.

```powershell
echo "foldernaam/" >> .gitignore
git add .gitignore
git commit -m "chore: keep local runtime artifacts out of git"
```

