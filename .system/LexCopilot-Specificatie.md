Markdown
# LexCopilot — Specificație conceptuală și arhitectură

*Document de lucru — versiune inițială. Se completează pe măsură ce se clarifică noi aspecte.*

---

## 1. Viziune

LexCopilot este un asistent AI destinat **avocaților independenți** din România (utilizabil și de firme mai mari), care:

- oglindește complet dosarul de instanță al avocatului (documente, scan-uri, înregistrări audio, transcripturi);
- redactează și perfecționează documente juridice (cereri de chemare în judecată, note de ședință, schițe de pledoarie, întrebări pentru martori etc.), pe baza legislației aplicabile **la data relevantă** și a conținutului dosarului;
- verifică fiecare document printr-o **simulare adversarială multi-agent** (reclamant / pârât / judecător) înainte de a-l preda avocatului;
- rămâne strict un **instrument de asistență** — avocatul citește, ajustează, semnează și trimite totul manual. Produsul nu are capacitate de trimitere automată a documentelor.

**Poziționare:** nu un substitut al avocatului, ci o "echipă de asistenți juridici" pentru avocatul care nu are resurse interne de documentare/cercetare.

**Argument de vânzare central:** claritate structurală + rigoare legislativă verificabilă = avantaj competitiv față de documente stufoase, prost organizate, ale părții adverse.

**Diferențiator cheie — experiența judecătorului, nu doar a avocatului:** documentele generate sunt optimizate și pentru cine le citește de partea instanței (judecătorul, în sala de consiliu, pe calculator) — mai ales în penal, unde pot exista zeci de înregistrări audio-video pe care judecătorul ar trebui, ideal, să le examineze direct, nu doar prin transcript. Un click pe o referință din text duce direct la segmentul exact al înregistrării, fără căutare manuală prin CD-uri sau timecode-uri. Ipoteza de adopție: valoarea reală a produsului devine evidentă pentru avocați în momentul în care primesc feedback pozitiv chiar de la judecători despre claritatea și structura concluziilor lor (inclusiv scheme/diagrame).

---

## 2. Utilizatori țintă

- **Primari:** avocați independenți, fără echipă/asistenți proprii.
- **Secundari:** firme mai mari, cu colaboratori pe dosare individuale.
- Client caracterizat prin: sensibilitate la preț, lipsă de infrastructură IT proprie, nevoie de simplitate ("plug and play").
- **Recomandare de utilizare (nu cerință tehnică):** tabletă de format mare, cu autonomie ridicată și interfață tactilă, pentru utilizare directă în sala de judecată. Produsul rămâne o aplicație web, deci funcțională pe orice dispozitiv cu browser — tableta e doar profilul de hardware recomandat pentru contextul de utilizare la instanță.

---

## 3. Principii fundamentale (non-negociabile)

1. **Surse oficiale de adevăr (nu unică, ci multiple, verificate încrucișat):** exclusiv text publicat oficial în Monitorul Oficial — prin două canale independente: (a) API-ul SOAP de la portal.just.ro, și (b) PDF-urile oficiale ale Monitorului Oficial, cu text nativ, identice cu varianta tipărită. Nu se folosesc versiuni consolidate neoficiale (Lege5, Sintact etc.). **Verificarea încrucișată se face act cu act** — se compară ce s-a extras/parsat din XML pentru un anumit act cu ce scrie efectiv în PDF-ul MO pentru **exact același act** (nu o comparație cu vreo formă „reconstituită la o dată", care nu există ca document publicat de MO). Dacă o lege e republicată oficial, republicarea e un act cvasidistinct nou, ingerat separat, atât în XML cât și în PDF — nu o versiune sintetizată intern.
2. **Imutabilitate:** actul normativ original nu se editează niciodată când e modificat de un alt act. Fiecare act (original + fiecare modificare + fiecare republicare oficială) e XML-izat ca document distinct, permanent.
3. **Reconstrucție la cerere, nu bază statică:** nu există o "lege la zi" stocată. Agentul Grefier pregătește contextul legislativ pentru o speță **fără să țină cont de o dată anume** — adună tot materialul brut relevant (act original + lanț complet de modificări), nescopat pe dată. **Fiecare agent din Arenă reconstituie independent** legea aplicabilă datei (sau datelor) de referință relevante pentru el, ca parte a propriului raționament. Dacă apar diferențe între agenți (foarte posibil la legi cu multe modificări succesive, sau unde intervin CCR/RIL/HP), acestea sunt dezbătute direct în Arenă, exact ca într-o instanță reală — eliminând astfel un single point of failure și valorificând logica adversarială a mai multor agenți AI independenți.
4. **Interzicerea raționamentului din memoria de antrenament:** agentul de reconstrucție trebuie să folosească strict textele din context (XML), nu cunoștințe din pre-antrenare. Dacă identifică o nevoie de text legal nefurnizat, trebuie să-l ceară explicit din baza XML, nu să-l reproducă din memorie.
5. **Semnalarea lacunelor:** dacă un act necesar lipsește din baza de date, agentul trebuie să semnaleze explicit acest lucru avocatului, nu să continue tăcut.
6. **Trasabilitate completă:** fiecare document generat conține o anexă cu istoricul complet (referințe MO) al fiecărui text de lege citat.
7. **Fără trimitere automată:** produsul nu trimite niciodată nimic direct (email, depunere la instanță). Avocatul face manual trimiterea/semnarea.
8. **Documentul din sistem nu e niciodată oficial:** chiar și forma finală, "călită" prin Arenă, rămâne un draft. Devine oficial doar după ce avocatul îl salvează ca PDF, îl semnează electronic cu mijloacele proprii și îl trimite pe mail la grefa instanței — acel gest de semnare locală e modul prin care avocatul își asumă documentul. Nu sunt necesare watermark sau integrare cu un provider de semnătură electronică în sistem.
9. **Arhivare hermetică (export la închidere):** nu e un mecanism activ/curent, ci o capacitate de export — avocatul poate exporta întregul dosar, exact așa cum e reprezentat în sistem, atunci când dosarul se închide definitiv sau colaborarea cu clientul încetează. Arhiva nu poate fi folosită local ca atare — poate fi doar reîncărcată ulterior în sistem, dacă e nevoie (ex. apariția unei căi extraordinare de atac — recurs etc. — după o decizie definitivă).

---

## 4. Arhitectura datelor legislative

### 4.1 Ingestie
- **Sursă:** portal.just.ro (legislație, decizii CCR, RIL, HP/ICCJ).
- **Strategia de colectare brută (decuplare totală):** un script extern, independent, rulează asincron și continuu, cu scopul exclusiv de a descărca toate actele normative în format brut și de a le salva într-un storage cloud dedicat. Scriptul **nu** execută nicio operație de parsare, structurare sau interpretare.
- **A doua sursă, independentă — arhivă oficială Monitorul Oficial în PDF:** pe lângă API-ul SOAP de mai sus, un al doilea colector descarcă direct PDF-urile oficiale ale Monitorului Oficial, cu **text nativ** (nu scanări, deci fără nevoie de OCR). Disponibile din **anul 2000** încoace; există promisiuni ale instituției de a digitiza și anii anteriori la un moment dat. Rolul acestei surse: verificare **act cu act** — ce s-a parsat din XML pentru un anumit act, comparat cu ce scrie efectiv în PDF-ul MO pentru **exact același act** (MO nu publică nicio formă „reconstituită la o dată" cu care să se compare — doar acte discrete, individuale; o republicare oficială e ea însăși un act cvasidistinct, ingerat separat). Fiind imaginea exactă a publicării, PDF-ul are prioritate ca sursă de adevăr în caz de discrepanță.
- **Fără prioritizare pentru MVP:** prin pornirea timpurie și independentă a acestor colectoare, sistemul are deja stocată toată legislația la zi (Constituția, codurile, legile organice și ordinare) în format brut, încă din momentul în care platforma principală intră în teste — elimină nevoia unei ordini de prioritizare a ingestiei.
- **Actualizare continuă:** odată ce storage-ul istoric e complet, task-ul devine o rutină nocturnă/de weekend, pentru a aduce doar actele noi și modificările.
- **Parsare și indexare — etapă separată, amânată:** transformarea datelor brute în arborele relațional din baza de date (vezi 4.2) și vectorizarea în Qdrant (vezi 4.3) sunt amânate și se execută centralizat, doar atunci când aplicația principală și pipeline-ul de business sunt gata pentru faza de testare.

### 4.1.1 Stocarea fișierelor XML brute, arhivate și indexate

Toate datele brute provenite de la API-ul SOAP (portal.just.ro) sunt salvate direct pe Google Drive (Shared Drives) conform unei strategii hibride optimizate pentru spațiu, viteză de acces și lizibilitate[cite: 2].

#### **1. Niveluri de stocare (Individual vs. Arhive `.tar.gz`)**
- **Fișiere individuale brute (`brut_XML_<act_id>.xml`):** 
  - Fișierele XML noi sau procesate recent sunt salvate inițial individual[cite: 2].
  - Permite acces rapid, atomic, fără a fi nevoie de dezarhivare pentru intervenții punctuale[cite: 2].
- **Arhive de grup per interval/an (`brut_XML_<interval>.tar.gz`):**
  - Pentru a evita atingerea limitelor de număr de fișiere (inodes / file-count limits) din Google Drive, fișierele vechi sau istorice sunt grupate cronologic (ex: `1990-1999.tar.gz`, `2000-2009.tar.gz`) și comprimate `.tar.gz`[cite: 2].
  - Reduce masiv overhead-ul de API Google Drive la citire/scanare[cite: 2].

#### **2. Sistemul de indexare (Index Global vs. Micro-indecși)**
Pentru a asigura acces instantaneu la orice fișier (fără a descărca sau deschide arhive mari la întâmplare), se folosește o arhitectură de indexare distribuită:

- **Micro-indecși per interval / sesiune (`micro_index_<interval>_<timestamp>.json`):**
  - Scriptul extern de descărcare generează automat fișiere mici de index JSON la fiecare rulare/slot din matrice[cite: 2].
  - *Conținut:* O mapare directă între numele fișierului XML (`brut_XML_<act_id>.xml`) și locația sa exactă:
    - `drive_id` (Shared Drive-ul unde se află)[cite: 2];
    - `tip_stocare` (`"individual"` sau `"arhiva"`)[cite: 2];
    - `arhiva` (numele fișierului `.tar.gz` în care a fost împachetat, dacă e cazul)[cite: 2].
- **Indexul Global Centralizat (`index_global_xml.json`):**
  - Un job de mentenanță unește periodic toți micro-indecșii într-un **Index Global master**[cite: 2].
  - **Rol:** Când un agent (ex: Grefierul) solicită un act normativ specific după `act_id`, sistemul interoghează Indexul Global în $O(1)$[cite: 2]:
    1. Dacă fișierul e stocat **individual**, este descărcat direct via Google Drive API[cite: 2].
    2. Dacă fișierul e stocat **în arhivă**, sistemul extrage *exclusiv* fișierul XML cerut din `brut_XML_<interval>.tar.gz`, fără a dezarhiva tot pachetul pe disc[cite: 2].

### 4.2 Structura de date
- **Model structural generic (arbore, nu coloane fixe):** nu toate actele au aceeași ierarhie (unele nu au capitole, unele au anexe cu numerotare proprie etc.). Se folosește un tabel unic de „noduri" auto-referențiate: `id, act_id, parinte_id, tip_nod (carte/titlu/capitol/secțiune/articol/alineat/literă/punct/anexă/text — listă deschisă), eticheta, ordine, text, notă, dată_intrare_în_vigoare`. Data intrării în vigoare trebuie să poată fi atașată și la nivel de nod individual (nu doar la nivelul actului), pentru cazurile de vacatio legis diferențiat pe articole. Reconstrucția XML e un parcurs recursiv al arborelui, indiferent de câte niveluri/ce tip de structură are actul respectiv.
- **Sursă de adevăr = bază de date relațională, nu fișiere XML.** Fiecare fragment (nod din arbore, plus notele de subsol atașate nodului relevant) e stocat structurat. XML-ul devine un **format de export/prezentare**, regenerat la cerere din arbore (pentru afișare către avocat, anexa de trasabilitate, arhivare) — nu mai e sursa primară de stocare.
- **Validare la ingestie:** înainte de a adăuga datele în baza principală, se populează o structură temporară identică, apoi se rulează algoritmul de reconstrucție XML pe ea și se verifică identitatea cu originalul publicat, ca test round-trip anterior commit-ului.
- **Chunking pentru vectorizare generat sistematic din arbore:** pentru fiecare nod terminal relevant, indexat după `act_id + id_nod`, textul de vectorizat e o concatenare a contextului ierarhic (titlu carte, capitol etc.) + textul de bază al articolului/alineatului/literei. Un articol simplu dintr-o lege fără subdiviziuni dă un string scurt; un fragment adânc dintr-un cod mare vine cu tot contextul ierarhic necesar sensului semantic.
- **Jurisprudență (CCR, RIL, HP/ICCJ, cazuistică ICCJ/Curți de Apel/tribunale):** nu necesită structurare completă pe fragmente — indexată strict după articolul/legea la care face referire.
- **Structură de referințe (graf de acte), ca tabelă separată de „modificări":** parte din aceeași bază de date relațională, actualizată la fiecare ingestie nouă. Nu se pun referințe direct pe tabelul de noduri (un nod poate fi modificat de mai multe acte succesiv, un act poate modifica mai multe noduri din mai multe legi — relație multi-la-multe cu atribute proprii). În schimb, o tabelă separată de tip „edges": `id, act_modificator_id, nod_țintă_id, tip_modificare (abrogare_totală/abrogare_parțială/modificare_text/completare/republicare), dată_aplicare, referință_MO`. Permite interogare în ambele sensuri (ce a modificat X / ce a fost modificat de Y) fără ca agentul să trebuiască să caute prin tot corpusul de fiecare dată. Notele de subsol din formele republicate oficiale pot servi ca sursă de validare încrucișată pentru acest graf.

### 4.3 Căutare semantică
- Fiecare articol / combinație articol+alineat+literă e **vectorizat** (model de embedding OpenAI, 3000+ dimensiuni) și stocat în **Qdrant**.
- Qdrant servește **doar** ca punct de plecare pentru căutare semantică (recall) — nu conține metadate de valabilitate temporală.
- Rezultatele din Qdrant sunt un input pentru selecția capitolelor/XML-urilor pe care Grefierul le adună ca material brut (vezi 4.4) — Grefierul **nu** decide valabilitatea temporală sau relevanța finală a niciunui fragment. Acea decizie rămâne, conform arhitecturii stabilite, exclusiv în sarcina fiecărui agent din Arenă, independent (vezi 5.1), inclusiv verificarea deciziilor CCR asociate.

### 4.4 Agentul AI Grefier — construcția contextului brut (fază distinctă, anterioară analizei/redactării)
- Primul pas, înainte de orice analiză sau redactare propriu-zisă, este definirea unui **context legislativ complet, dar optimizat** — realizat de un rol dedicat, denumit **Grefierul Virtual**, separat complet de faza de dezbatere (Arena, vezi 5.1).
- **Grefierul NU stabilește forma aplicabilă la o dată anume** — acea decizie interpretativă rămâne strict în sarcina agenților din Arenă (vezi mai jos, principiu important). Rolul Grefierului e să adune tot materialul brut relevant, nescopat pe o singură dată, nu să-l reducă la o singură formă „corectă".
- Agent cu fereastră mare de context (candidat: Gemini) primește doar **capitolele relevante** (nu legea integrală) — cele care conțin fragmentul găsit prin căutare semantică — pentru actul de bază și pentru tot lanțul de acte care l-au modificat succesiv.
- **Completare iterativă de context, la cerere:** Grefierul examinează contextul primit inițial și, dacă identifică trimiteri interne nerezolvate (ex. Codul rutier definește infracțiunile într-un capitol, iar pedepsele sunt într-un capitol separat, la final) sau referințe punctuale către alte legi, cere explicit capitolele suplimentare necesare (cu tot lanțul lor de acte modificatoare) — nu presupune conținutul din memoria proprie.
- **Bucla rulează până la convergență** — poate necesita mai multe iterații de cerere/completare, până când Grefierul nu mai identifică lacune. Costul suplimentar e acceptat în schimbul unui context complet și precis.
- **Adăugare jurisprudență cu forță obligatorie:** se adaugă, în **text integral** (spre deosebire de legislație, care e scoped pe capitole), toate deciziile CCR, RIL-urile și HP-urile ICCJ relevante pentru legile/articolele din contextul deja adunat.
- **Sigilarea contextului:** odată ce Grefierul consideră dosarul legislativ complet (tot lanțul de modificări relevante, nescopat pe o dată), generează contextul final unitar, **randat în XML** din arborele bazei de date, ca structură clară pentru agenții din Arenă — permite referențierea exactă a textelor (paragraf integral, literă etc.) atât în raționament, cât și în citările din documentul final.
- Grefierul folosește **doar** raționament asupra textelor primite din baza de date, niciodată din memoria proprie.
- Rezultatul e un document temporar, sigilat, intern — avocatul nu primește "legea la zi" ca atare.

### 4.5 Jurisprudență cazuistică — utilizare selectivă, distinctă de CCR/RIL/HP
- Spre deosebire de CCR/RIL/HP (forță de interpretare general obligatorie, adăugate mereu în contextul de bază), jurisprudența cazuistică (ICCJ și instanțe inferioare) **nu** e adăugată implicit în faza de construcție a contextului.
- Se folosește **selectiv**, doar în anumite situații unde chiar adaugă valoare — ex. la concluzii finale — și numai dacă e de folos, nu ca sursă implicită pentru orice document.
- **Fără prag statistic fix, configurat în sistem:** agentul produce o analiză a jurisprudenței aplicabile (de la ICCJ în jos), dar decizia dacă și cât din ea se folosește rămâne a avocatului, după ce studiază analiza — nu un procent automat de invocare.

### 4.6 Validarea algoritmului de reconstrucție (plan pentru faza de testare)
Distinct de verificarea act-cu-act de la ingestie (4.1), odată ce sistemul de reconstrucție (arbore + graf de modificări + selecție de formă aplicabilă) e funcțional, se face un test manual de validare a **calității reconstrucției** — nu a fidelității ingestiei:

- Se reconstituie manual câteva legi, pentru date de referință specifice, folosind algoritmul propriu.
- Rezultatul se compară cu **două repere externe independente**:
  1. **legislatie.just.ro** (portalul oficial — aceeași sursă de bază, dar cu propriul lor mecanism de consolidare/afișare „text valid la data curentă")
  2. **Lege5** (sursă comercială, independentă, folosită de ani de zile de avocați)
- **Interpretare:** dacă toate trei converg, încredere solidă. Dacă portalul oficial și Lege5 sunt de acord, dar reconstrucția proprie diferă, problema e la algoritmul propriu. Dacă toate trei diferă, e un caz de graniță de investigat manual direct în MO — posibil chiar o eroare la sursa oficială.
- Legi recomandate pentru test: cele cu istoric bogat de modificări (ex. Codul muncii, Codul fiscal), și date de referință alese intenționat aproape de momentul unei modificări recente, ca să testeze exact granițele temporale.

---

## 5. Motorul de redactare și verificare

**Agentul redactor** intră în acțiune **după** cele 3 runde de dezbatere din Arenă — sintetizează concluzia finală. E responsabil nu doar de forma optimizată a documentului final, ci și de a scrie explicațiile despre disputele apărute în Arenă, inclusiv raționamentul câștigător care a determinat forma finală a fiecărui pasaj contestat.

### 5.1 Simulare adversarială multi-agent (Arena)
- Pentru fiecare document generat/perfecționat: simulare cu roluri **reclamant / pârât / judecător**, ~3 runde, denumită **Arena** — fază complet separată de construcția contextului (Grefier, vezi 4.4).
- **Componență adaptabilă:** rolurile simulate nu sunt fixe la reclamant/pârât/judecător — se adaptează la participanții reali ai dosarului. Dacă un **procuror** participă la un proces non-penal (situații prevăzute de Codul de procedură civilă — ex. cazuri cu minori, persoane puse sub interdicție, interes public), rolul lui e simulat și el în Arenă. **Fiecare intervenient prezent în dosar primește propriul agent de simulare dedicat** — nu e doar opțional, ci o cerință, ori de câte ori apare un intervenient.
- **Simularea operează exclusiv pe documente text** — conținutul multimedia din dosar (audio, video) intră în simulare doar prin stratul lui text deja procesat (transcript, descriere vizuală), nu ca fișiere media propriu-zise. Toată complexitatea de procesare media rămâne izolată în etapa de ingestie a dosarului.
- **Context legal comun, sigilat de Grefier — dar nescopat pe o dată aplicabilă:** contextul legislativ + jurisprudențial finalizat (vezi secțiunea 4.4) e trimis identic tuturor agenților din Arenă — toți lucrează de pe aceeași bază de referință brută. Adversitatea se dă pe argumente, omisiuni, excepții, interpretare — nu pe diferențe de acces la sursele legale.
- **Determinarea formei aplicabile e sarcina fiecărui agent din Arenă, independent — nu a Grefierului.** Fiecare agent își construiește propriul cadru legal aplicabil pentru data (sau datele) relevante ale spetei, ca parte a propriului raționament argumentativ. Motiv: elimină un single point of failure — alegerea formei aplicabile nu e mereu mecanică (ex. decizii CCR relevante, sau cazuri penale unde trebuie identificată legea penală mai favorabilă — *lex mitior* — pe un interval), iar prin iterațiile succesive ale Arenei, o eroare de selecție a formei aplicabile are șanse mai mari să fie prinsă decât dacă un singur agent (Grefierul) ar fi decis unilateral de la început.
- **Instrucțiune de sistem strictă pentru agenții din Arenă:** primesc dosarul legislativ brut sigilat de Grefier cu interdicție explicită de a folosi orice definiție, articol, excepție sau interpretare din propria memorie de antrenament — dacă o normă nu se regăsește în documentul sigilat, pentru raționamentul lor ea nu există în dreptul românesc.
- **Beneficii ale separării Grefier/Arenă:** agenții din Arenă nu mai pierd resurse „căutând" legi sau verificând valabilitatea temporală (asta e deja rezolvat de Grefier) — își pot folosi capacitatea integral pentru strategie juridică, atac și apărare; toți primesc exact același dosar, deci dezbaterea e obiectivă, pe argumente, nu pe asimetrie de informație între agenți.
- **Ideal:** fiecare rol jucat de o platformă AI diferită (ex. Claude, ChatGPT, Gemini), pentru adversitate reală, nu doar aparentă.
- Scop: documentul "călit" rezistă la contra-argumente înainte să ajungă la instanța reală.
- Se aplică nu doar cererii de chemare în judecată, ci și note de ședință, schițe de pledoarie, întrebări pentru martori — orice output redactat de sistem.

### 5.2 Structura documentelor ample
Pentru documente substanțiale (cerere de chemare în judecată, note de concluzii, note de ședință la dosare complexe, documente pentru schimbare de judecător etc.), pe lângă cerințele din codurile de procedură:

1. **Executive summary** (sub 5 pagini) — sinteza întregului document, fără citate din legi sau probe. Avocatul poate opta să nu se genereze, dacă documentul e scurt și esențialmente tehnic.
2. **Corpul complet** — toate detaliile din probe, texte de lege citate ca fragment relevant (bază articol + [...] + alineat relevant + [...] + literă relevantă, nu articolul integral), lungime cât e necesar scopului.
3. **Anexă de tracking legislativ** — pentru fiecare text de lege citat în corp, istoricul complet din MO, cu referințe integrale. Acolo unde alegerea formei aplicabile a fost o decizie interpretativă (nu una mecanică — ex. relevanța unei decizii CCR, sau *lex mitior*), anexa reflectă și motivul pentru care acea formă a fost aleasă ca aplicabilă de agenții din Arenă.

### 5.3 Modulul Cameleonic — vizualizări (diagrame/scheme)
- Bifă activabilă în interfață, per document:
  - **Activă (default):** documentul include elemente de Legal Design — tabele de corespondență, linii temporale, scheme sobre (nuanțe de bleumarin și gri), generate de agentul redactor acolo unde consideră necesar.
  - **Dezactivată:** conținutul echivalent e tradus instantaneu în text juridic pur, dens, tradițional — fără elemente grafice.
- Generate ca **pas final**, pe forma deja perfecționată a documentului (nu în timpul procesului).
- Avocatul dezactivează bifa dacă știe că judecătorul ar putea privi nefavorabil o astfel de abordare.

### 5.4 Structura PDF-ului final pentru instanță (anexe și hyperlinkuri)
- **Anexă unificată de probe:** toate probele invocate în documentul principal sunt organizate centralizat, într-o anexă dedicată.
- **Hyperlinkuri intradocument cu revenire, plus referință text de rezervă:** fiecare mențiune a unei probe din corpul documentului conține un link direct către poziția ei din anexă (cu link de revenire în anexă către paragraful de plecare) **și** o referință text explicită (ex. „vezi nota XX din pagina yy a documentului"), pentru situațiile unde hyperlinkurile nu se păstrează (printare etc.).
- **Probe AV — acces integrat în dosar, fără permisiuni separate:** probele audio-video sunt trunchiate exact la segmentul corespunzător transcriptului inclus în document și puse la dispoziție prin legături web criptice, non-indexabile, fără opțiune facilă de download în interfață. Securitatea lor e **subsidiară securității întregului dosar** (complet confidențial) — orice utilizator autentificat cu acces legitim la dosar are automat și acces la vizualizarea probelor media. Nu se construiește un mecanism de permisiuni separat, extra-complex (ex. dedicat exclusiv judecătorilor/grefierilor din afara sistemului).
- **Subtitrare automată obligatorie a tuturor probelor AV:** toate probele audio-video sunt subtitrate — nu doar pentru accesibilitate, ci și ca mecanism de verificare (permite descoperirea vizuală a eventualelor greșeli de transcript). Probele audio (mp3) sunt convertite într-un mp4 cu un carton static afișând numele probei, peste care rulează subtitrarea generată din transcript; probele deja video primesc subtitrarea suprapusă direct.
- **Limită de dimensiune: PDF-ul final sub 10 MB.** Multe instanțe (confirmat: Judecătoria Sector 6) resping fișiere mai mari la depunere electronică — probabil o limitare comună, nu izolată. Textul generat de sistem nu se apropie de această limită; fișierele multimedia rămân în cloud (doar link-uri, nu embed direct în PDF) — sursa principală de risc sunt **imaginile scanate** incluse ca probe. Acestea trebuie super-optimizate ca JPG înainte de inserare în PDF, convertite în tonuri de gri atunci când conținutul e o scanare/fotografiere rapidă de document (nu o fotografie color cu semnificație proprie, unde culoarea contează).
- **Grupare pe PDF-uri anexă separate, dacă e nevoie:** probele-imagine pot fi grupate în unul sau mai multe PDF-uri anexă distincte (separate de documentul principal, atașate la final), fiecare menținut sub **9 MB** (marjă de siguranță sub limita de 10MB), ca să se încadreze sigur în limitele de upload ale instanțelor.

### 5.5 Captare rapidă de conținut ("pe teren")
- Avocatul poate da **indicații vocale sau text** sistemului (ex. imediat după o ședință, din mașină/pe hol) pentru redactare rapidă.
- Aceste indicații sunt **material de lucru intern**, nu apar ca atare în dosar.

### 5.6 Analize de lucru pe subiect
- Pe lângă redactarea de documente pentru instanță, avocatul poate cere (vocal sau text) **analize ca documente de lucru intern**, pe un subset tematic al dosarului — ex. analiză pe prescripții, pe culpe, pe penalități.
- Aceste analize trec și ele prin simularea adversarială de „călire" (algoritmul e același, indiferent de tipul de output) — un singur motor de redactare/verificare, aplicat uniform peste orice document produs de sistem, nu doar peste cele destinate instanței.

---

### 5.7 Input-ul avocatului la generare
- La orice document generat, avocatul poate furniza un draft propriu sau doar câteva idei de pornire.
- **Cererea de chemare în judecată:** input **obligatoriu** — avocatul trebuie să specifice ce vrea și cum vrea, pentru că intenția/strategia inițială nu poate fi dedusă de agenții AI (dosarul nici nu există încă în formă completă la acel moment).
- **Alte documente** (note de ședință, schițe de pledoarie etc.): input **opțional** — avocatul poate da idei de pornire, inclusiv o cerere de căutare prin jurisprudență pentru o temă ce urmează să fie dezbătută la termenul următor; sistemul poate genera și fără input explicit, pe baza contextului deja existent în dosar.

### 5.8 Integrare calendar și task-uri
- Termenele cauzei (inclusiv instanța și locația unde trebuie să se prezinte avocatul) sunt puse automat în calendarul avocatului.
- **Avertisment cu câteva zile înainte** de fiecare termen, ca reminder să-și actualizeze dosarul din ECRIS și să-și pregătească documentele pentru ședință.
- **Alte deadline-uri de îndeplinit** (ex. redactat și trimis întâmpinarea, note de ședință etc.) sunt reflectate atât în calendar, cât și în task list-ul avocatului.

### 5.9 Tipuri de documente generate — prompturi standard per tip
Fiecare tip de document are propriile constrângeri de scop, lungime și ton, definite printr-un prompt standard care focalizează agentul redactor pe obiectivul principal al acelui document și îl împiedică să elaboreze conținut irelevant scopului. Lista de documente disponibile pentru un dosar se filtrează după statusul curent al dosarului (vezi 6.0) — ex. „motive de apel" nu apare disponibil pentru un dosar aflat la fond.

Listă (de completat/rafinat la implementare):

- Cerere de chemare în judecată
- Precizare/completare de acțiune
- Întâmpinare
- Răspuns la întâmpinare
- Ridicare de excepții
- Cerere de probe
- Note prealabile de ședință
- Concluzii scrise intermediare (pe un incident procedural punctual)
- Pledoarie recomandată
- Întrebări pentru martori
- Concluzii finale
- Document de referință pentru judecătorul nou (la schimbare de complet) — ton neutru, complet, fără caracter de pledoarie, spre deosebire de restul documentelor
- Contestație la executare
- Cerere de suspendare a executării
- Cerere de recuzare
- Cerere de strămutare a cauzei
- Notificare/somație prealabilă (etapă precontencioasă)
- Cerere de apel + motivele de apel (documente separate)
- Întâmpinare la apel
- Cerere de recurs + motivele de recurs (documente separate)
- Întâmpinare la recurs
- Cerere de revizuire (cale extraordinară)
- Contestație în anulare (cale extraordinară)
- Cerere de ajutor public judiciar / scutire de taxe
- **Ordonanță președințială** — necesită obligatoriu argumentarea celor 3 criterii standard: urgența, caracterul vremelnic, neprejudecarea fondului; prompt-ul standard trebuie să forțeze acoperirea explicită a fiecăruia
- *(listă deschisă — de extins pe măsură ce apar necesități specifice)*

---

## 6. Gestiunea dosarului

### 6.0 Inițierea unui dosar
- **Titlu de lucru:** dat de avocat la creare, intuitiv, se păstrează pe durata dosarului — singura verificare necesară e cea de duplicat (nu se permit două dosare cu exact același titlu).
- **Cheie de dosar:** inițial dosarul e identificat doar prin titlul de lucru; **numărul de dosar ECRIS se adaugă atunci când apare** (nu toate dosarele au un număr ECRIS de la început — ex. înainte de înregistrarea acțiunii), moment din care devine cheia principală a dosarului în sistem.
- **Definirea părților:** obligatorie la inițiere. Include, pe lângă reclamant/pârât, și eventuali **intervenienți**. Pentru fiecare parte se definește **statutul** (rolul procesual). **Lista de părți e dinamică** — nu toți intervenienții sunt prezenți de la început, pot fi adăugați pe parcursul procesului; componența Arenei (vezi 5.1) se actualizează corespunzător.
- **Adresă de corespondență per parte, editabilă:** pentru celelalte părți, de obicei sediul cabinetului avocatului lor, altfel domiciliul — câmp editabil, nu dedus automat.
- **Status dosar:** în pregătire / fond / apel / recurs / cale de atac extraordinară. Lista de tipuri de documente disponibile pentru redactare (vezi 5.9) se adaptează statusului curent al dosarului.
- **Instanță, secție, complet — per etapă procesuală:** se definesc separat pentru fiecare status/etapă a dosarului (fond, apel, recurs etc.), pentru că pot diferi de la o etapă la alta.
- **Disciplina/materia dosarului:** civil, penal, contencios administrativ și fiscal, familie, muncă și asigurări sociale, mediu, comercial/societar, imobiliar/cadastru, proprietate intelectuală, contravențional, executare silită, litigii privind partide politice (electoral etc.) — *(listă deschisă, de extins la implementare)*.

- LexCopilot **oglindește complet** conținutul dosarului de instanță: documente, scan-uri, înregistrări audio (mp3 etc.) — atât în format brut, cât și ca transcript.
- Avantaj central: acces instant și complet la tot dosarul, fără limitările memoriei umane, corelat cu baza legislativă completă, la orice moment.

### 6.1 Ingestia documentelor de dosar
- **Sursă:** upload manual de către avocat — inclusiv documente descărcate manual din ECRIS (fără API disponibil/de așteptat pentru acces automatizat la ECRIS, considerat subiect delicat cu autentificare complexă).
- **Principiu de conținut:** secțiunea de documente brute conține **exclusiv** ce provine din ECRIS (inclusiv documentele redactate și trimise de avocat, odată intrate oficial în dosar) — pentru că asta reflectă exact ce văd instanța și celelalte părți din proces. Documentele generate de LexCopilot dar netrimise încă (draft-uri, analize interne) rămân separate, ca material de lucru, până devin ele însele parte din ECRIS.
- **Tipuri:** PDF-uri cu text nativ, PDF-uri scanate, JPG-uri fotografiate, MP3-uri, MP4-uri.

### 6.2 Structurare — principiu diferit față de legislație
- **Nu se forțează un XML ierarhic** de tip articol/alineat peste documentele de dosar (spre deosebire de legislație, unde structura e impusă și stabilă din exterior) — fiecare tip de document de dosar are formă proprie, adesea neformalizată.
- **Metadate structurate** per document: tip, dată, sursă (ECRIS/upload manual), parte care l-a depus, termen/ședință asociat.
- **Conținutul propriu-zis** (text extras sau transcris) e stocat pe **unități naturale ale documentului** (ex. intervenție per vorbitor, cu marcaj de timp, pentru proces-verbal de ședință), nu impus într-o ierarhie legislativă. Vectorizat și indexat în Qdrant, similar legislației.

### 6.3 Tabele din documente scanate/expertize
- Risc major identificat: extragerea corectă a tabelelor din scan-uri (calcule, măsurători, sume) — OCR clasic e slab la structură tabelară.
- Abordare: model AI multimodal (nu OCR clasic) pentru extragere, cu flag de încredere scăzută pe pasajele/tabelele incerte, recomandare de verificare manuală. Documentul original rămâne mereu accesibil ca referință.

### 6.4 Transcriere audio
- Toate transcriptele audio au **timecode**.
- Două categorii cu nevoi diferite: **înregistrări de ședință** (diarizare — cine vorbește, corelare cu termenul din dosar) și **probe audio** (calitate variabilă, flag de încredere pe pasaje neclare, integritate critică pentru argumentare).
- Transcriptul e o interpretare/strat de căutare — fișierul audio original rămâne sursa de adevăr.

### 6.5 Conținut video (AV)
- Pe lângă transcriptul audio (cu timecode), se generează un **strat descriptiv vizual**: extragere de cadre-cheie (interval regulat sau schimbări de scenă), descrise text prin model AI multimodal, cu timecode atașat — vectorizat/căutabil similar restului conținutului.
- Descrierea vizuală e o interpretare AI, cu flag de încredere pe detalii critice (plăcuțe, identificare persoane, ore afișate) — proba video originală nu poate fi niciodată înlocuită, doar parsată/indexată pentru a ușura căutarea prin ea.

---

## 7. Model de cont și colaborare

- **Autentificare:** Google, Microsoft, sau Magic Link — fără parole, fără flux de resetare parolă.
- **Model multi-user:** fiecare **dosar** are un **OWNER**. Owner-ul adaugă/elimină colaboratori exclusiv el. Colaboratorii adăugați au **drepturi depline** (fără permisiuni granulare, fără nevoie de IT admin).

---

## 8. Tehnologie și implementare

- **Abordare:** solo, cât mai puțin cod posibil, scris de un AI coding assistant (nu developer angajat).
- **Componente probabile:**
  - Bază de date + autentificare: Supabase (Postgres, auth Google/Microsoft/magic link inclus)
  - Vector search: Qdrant Cloud
  - Orchestrare automatizări ușoare (task nocturn, notificări): Make
  - Ingestie/parsare legislație, orchestrare multi-agent, logică de business: cod dedicat (scris cu asistență AI, ex. Claude Code)
  - Hosting: platformă simplă tip Vercel/Railway
- **Alocare de roluri pe modele AI (orientativ):**
  - **Google Gemini** — orchestrator multimodal: procesarea dosarelor voluminoase (fereastră mare de context), OCR pe documente scanate, procesarea înregistrărilor audio/video din instanțe, rol de Grefier (vezi 4.4).
  - **OpenAI GPT-4o** — redactare fină: sinteză juridică de acuratețe, adaptare stilistică formală în limba română, unul din rolurile din Arenă.
  - **OpenAI (ChatGPT)** — desemnat ca specialistul pentru vectorizare/embeddings (consistent cu modelul de embedding OpenAI menționat la 4.3).
  - *(Ideea de a folosi platforme AI diferite pentru fiecare rol din Arenă — Claude, GPT, Gemini — rămâne principiul de bază pentru adversitate reală; alocarea exactă rămâne de rafinat la implementare.)*
- *(Notă: Google Sites + Airtable, sugerate inițial, nu pot susține complexitatea sistemului — vezi discuția din arhitectură.)*
- **Implementat deja (nu doar plan):** scripturile de colectare brută a legislației (ambele surse — API SOAP și PDF-uri MO) sunt scrise în **Python**, rulează pe **GitHub** (Actions, programate automat), cu stocarea fișierelor brute în **Google Drive** (Shared Drive).

---

## 9. Pricing (schiță, de dezvoltat)

- Idee inițială: 3 niveluri — bază (mai ieftin, limitat pe **număr de dosare**, nu funcționalități), volum, premium.
- Rafinare: tier-uri bazate pe numărul de dosare active **și** pe volumul de pagini procesate prin OCR (a doua dimensiune, relevantă pentru costul real de procesare al platformei).
- Nu e prioritate acum — se dezvoltă după clarificarea mecanicii produsului.

---

## 10. Strategie de lansare

- Prototip trimis către câțiva avocați cunoscuți personal, ca prim val.
- **Perioadă gratuită de 90 de zile pentru orice utilizator nou** (nu doar avocații cunoscuți inițial) — inclusiv acces la cele 3 dosare demo pre-încărcate.
- **Raționament de retenție:** dacă avocatul apucă să-și încarce propriile dosare în această perioadă și se obișnuiește cu documente optimizate generate practic instant, va fi greu să renunțe la produs după expirarea perioadei gratuite.
- **Dosare demo:** acces instant la 3 dosare pre-încărcate de complexitate ridicată, pentru ca utilizatorii noi să poată experimenta imediat Arena, fără să aștepte ingestia propriului lor dosar.
- Colectare feedback → iterare pe produs.

---

## 11. Interfață — principii de ergonomie

- **Captare rapidă, oricând, universal:** buton de captare vocală/text accesibil de oriunde din aplicație, nu îngropat în meniuri.
- **Comenzile vocale se leagă de un dosar, dar alocarea poate fi amânată:** pentru viteză (ca avocatul să nu uită o idee), înregistrarea se poate face direct, fără să aleagă întâi dosarul — se trimite ulterior spre procesare către dosarul corect (zonă intermediară de capturi nealocate, cu triere/confirmare explicită a avocatului înainte de procesare).
- **Dosarul ca unitate centrală de lucru** — punct de plecare pentru orice acțiune concretă (documente, context legislativ specific, colaboratori).
- **Separare vizuală clară „oficial" vs. „în lucru"** în interiorul unui dosar, reflectând principiul documentelor master (ECRIS) vs. draft-uri interne LexCopilot.
- **Trasabilitate navigabilă la revizuire** — ecranul de revizuire a unui document generat trebuie să permită navigare ușoară între corp și anexa de tracking legislativ (nu doar scroll lung), ideal cu citări clickabile.
- **Minimum de fricțiune la upload** — selecție/drag-and-drop simplu pentru documente ECRIS, poze, audio.

---

## 12. De clarificat / etape următoare

**Rezolvate:**
- [x] ~~Model de facturare pentru colaboratori~~ — Decis: detaliile se stabilesc în secțiunea de pricing, ce va fi definită ulterior.
- [x] ~~Decizia formei aplicabile la date specifice~~ — Decis: Grefierul nu mai scoapează/selectează textele legislative; decizia revine individual fiecărui agent din Arenă, pe baza logicii proprii. Agentul Redactor sintetizează concluzia finală după cele 3 runde de dezbatere.
- [x] ~~Gestiunea pe termen lung a probelor AV~~ — Decis: securitatea probelor AV e subsidiară securității întregului dosar. Cine are acces la dosar, are acces la probe. Legăturile sunt criptice și protejate de autentificarea generală.
- [x] ~~Ordinea exactă de ingestie (priorități MVP)~~ — Decis: nu există priorități; prin pornirea timpurie a scriptului extern de colectare brută, sistemul va avea acces la toată legislația la zi în momentul testării.
- [x] ~~Dezvoltarea scriptului extern de descărcare~~ — DEPĂȘIT: există acum **două** colectoare independente, funcționale: unul via API SOAP (portal.just.ro), unul via PDF-uri oficiale MO cu text nativ (din 2000). Ambele rulează idempotent (reluare automată din întreruperi, fără duplicate).
- [x] ~~Tratarea normelor materiale vs. procesuale în Arenă (inclusiv spețe cu mai multe date de referință)~~ — Decis: nu se definește o tehnică algoritmică separată. Agenții din Arenă aplică strict codurile de procedură civilă/penală (cu toate ajustările și modificările lor) pe speța primită — fie că e vorba de data producerii faptei, data semnării contractului, data începerii acțiunii, data sentinței finale, sau date de referință pentru infracțiuni multiple/continuate. E deja implicit în rolul agenților, care primesc mapa juridică de la Grefier — nimic suplimentar de definit.
- [x] ~~Criteriu de calitate/testare pentru embeddings pe text juridic românesc~~ — Decis: modelul de vectorizare e ChatGPT (OpenAI); testarea/validarea calității se va face live, în timpul folosirii reale a produsului, nu ca etapă separată de test înainte de lansare.

Toate punctele deschise sunt rezolvate — nu mai există rămășițe deschise în specificație. Orice detal
