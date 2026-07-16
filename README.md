Markdown# Specificație Tehnică: Sistemul de Sincronizare și Descărcare a Monitoarelor Oficiale (Partea I)

Sistemul este proiectat pentru descărcarea, monitorizarea și auditarea eficientă a tuturor edițiilor din Monitorul Oficial Partea I (anii 2000–2026), utilizând o arhitectură distribuită și paralelă prin GitHub Actions și stocare pe Google Shared Drive.

---

## 1. Arhitectura de Stocare și Variabile de Mediu

Pentru a evita hardcodarea ID-urilor de foldere și a securiza accesul, configurările sunt stocate în **GitHub Repository Variables & Secrets**:

*   **`GOOGLE_SERVICE_ACCOUNT_JSON`** *(Secret)*: Token-ul JSON de autentificare pentru Service Account-ul Google Cloud.
*   **`DRIVE_FOLDER_PDF`** *(Variable)*: ID-ul unicului Shared Drive dedicat pentru PDF-urile brute ale Monitoarelor Oficiale.
*   **`DRIVE_FOLDER_XML`** *(Variable)*: ID-ul folderului din Shared Drive dedicat XML-urilor parsite.

---

## 2. Registrele de Stare (`status_YYYY.csv`)

În loc de fișierele dummy (de 1 byte) individuale, starea fiecărui număr din fiecare an este urmărită centralizat într-un registru CSV dedicat per an, salvat în folderul rădăcină al Shared Drive-ului de PDF-uri sub denumirea `status_YYYY.csv` (ex: `status_2024.csv`).

### Structura CSV-ului:
```csv
numar,simplu,bis,tris,quatro,s
1,20,10,10,10,10
2,20,20,15,10,10
3,0,0,0,0,0
Linii: Fiecare registru conține exact 1500 de rânduri, corespunzătoare numerelor potențiale $1 \rightarrow 1500$ din anul respectiv.Coloane: numar (ID numeric), simplu, bis, tris, quatro, s (stările pentru fiecare tip de ediție).3. Matricea Codurilor de StareFiecare coloană de tip ediție din registru va conține una dintre următoarele valori numerice:Cod StareSemnificație LogicăAcțiune în Scriptul NormalAcțiune în Scriptul de Recuperare0 – 4Netestat sau Eșecuri Temporare. Reprezintă numărul curent de încercări de descărcare eșuate.Scriptul încearcă descărcarea normală. Dacă eșuează, starea se incrementează: $\text{Stare} \rightarrow \text{Stare} + 1$.Ignorat.5Limită Automată Atinsă. Prag intermediar de decizie.Scriptul nu mai încearcă descărcarea.- Dacă este număr SIMPLU $\rightarrow$ se promovează automat la 15 și se generează fișier _FAILED.pdf în Drive.- Dacă este SUFIX $\rightarrow$ se promovează la 10 (inexistent).Ignorat.10Inexistent Confirmat / Abandonat. Știm sigur că ediția specială nu există.Ignorat complet.Ignorat complet.15Eșec Critic - Obligatoriu de Recuperat. Fișierul simplu trebuie să existe, dar descărcarea automată a eșuat.Ignorat complet. În Drive există un fișier placeholder MO_PI_YYYY_N_FAILED.pdf care conține URL-ul direct.Scriptul special de recuperare (manual/browser) rulează exclusiv pe aceste înregistrări.20Descărcat cu Succes (OK). Fișierul PDF valid de dimensiune mare există în cloud.Ignorat complet.Ignorat complet.4. Reguli de Propagare și Optimizare (Sufixe)Pentru a reduce interogările inutile pe serverele externe și a economisi timp de execuție, se aplică următoarele reguli de propagare logică în registru:Propagare pe Inexistență Primară: Dacă un număr simplu este marcat ca 10 (inexistent), toate edițiile sale asociate (bis, tris, quatro, s) sunt promovate instantaneu la starea 10. (Dacă nu există numărul principal, este exclus logic să existe ediții secundare).Propagare pe Întrerupere Lanț: Dacă bis este marcat ca 10 (sau ajunge la limita 5 de eșec), atunci automat tris, quatro și s sunt propagate pe starea 10 (sufixele superioare nu pot exista fără cele inferioare).5. Separarea Workflow-urilor în GitHub ActionsPentru a maximiza performanța și a preveni blocarea sau încetinirea cauzată de timpii de așteptare (retry-uri/timeout-uri), procesul de descărcare este separat în două scripturi paralele:A. Scriptul de Numere Simple (descarca_monitoare_simple.py)Rulează pe o matrice paralelă agresivă de 6 mașini virtuale în GitHub Actions, divizată strict pe intervale de ani (ex: 2000-2005, 2006-2010 etc.).Deoarece fiecare instanță editează doar registrele din anii alocați, riscul de conflicte de scriere (race conditions) în Shared Drive este zero.Dacă un an înregistrează 60 de erori 404 consecutive pe numere simple, scriptul încheie automat procesarea acelui an (optimizare pentru anii finalizați).B. Scriptul de Sufixe (descarca_monitoare_sufixe.py)Rulează pe o logică dedicată monitorizării contoarelor de tip Bis, Tris, Quatro, S.Interoghează și verifică periodic doar numerele marcate ca fiind netestate în CSV-urile corespunzătoare.6. Scurtături Operaționale (Workflow-uri One-Off)muta_fisiere.py: Mutare server-to-server instantanee, la nivel de metadate Google API, din folderul vechi în noul Shared Drive.creeaza_registre_initiale.py: Script de migrare inițială care scanează fișierele deja descărcate în Drive și inițializează automat cele 27 de fișiere status_YYYY.csv cu stările corecte (20 pentru PDF-uri valide, 15 pentru failed, 0 pentru restul).7. Automatizare (Scheduling)După stabilizare, ambele fluxuri sunt setate în GitHub Actions să ruleze automat la fiecare 6 ore (cron: '0 */6 * * *'), asigurând o sincronizare perfectă aproape de timpul real cu publicațiile oficiale.
