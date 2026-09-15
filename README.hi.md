<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.md">English</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/audiobooker/main/assets/audiobooker-logo.png" alt="Audiobooker" width="480" />
</p>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/audiobooker-ai/"><img src="https://img.shields.io/pypi/v/audiobooker-ai" alt="PyPI"></a>
  <a href="https://www.npmjs.com/package/@mcptoolshop/audiobooker"><img src="https://img.shields.io/npm/v/@mcptoolshop/audiobooker" alt="npm"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  Turn <strong>EPUB / TXT / PDF / DOCX</strong> books into professionally narrated, multi-voice audiobooks — <strong>M4B / MP3 / Opus / FLAC / WAV</strong>, with chapter markers, cover art, and mastering to the <strong>ACX audio spec</strong>. From one command.
</p>

```bash
npx @mcptoolshop/audiobooker make mybook.epub --acx
```

ऑडियोबुकर संवाद का पता लगाता है, प्रत्येक पात्र के लिए एक विशिष्ट आवाज निर्धारित करता है, भावनाओं का अनुमान लगाता है, आपको किसी भी एक सेकंड को प्रस्तुत करने से पहले सब कुछ समीक्षा और सही करने देता है, फिर परिणाम को ACX ऑडियो विनिर्देश के अनुसार अनुकूलित करता है - इसलिए आउटपुट एक *तैयार* ऑडियोबुक है, न कि केवल उत्पन्न ऑडियो।

## इंस्टॉल करें

**शून्य-इंस्टॉल (नोड):**
```bash
npx @mcptoolshop/audiobooker --help
```

**पायथन (सीएलआई):**
```bash
pipx install audiobooker-ai            # isolated CLI
uvx audiobooker --help                 # zero-install trial
pip install "audiobooker-ai[render]"   # with the TTS voice engine
```

**डॉकर** - एफएफएमपीईजी पहले से ही इसमें मौजूद है, प्रत्येक रिलीज़ पर जीएचसीआर पर प्रकाशित किया गया:
```bash
docker run --rm -v "$(pwd):/data" ghcr.io/mcp-tool-shop-org/audiobooker \
  make /data/mybook.epub --acx
```
यह एक माउंट पर्याप्त है, और `--rm` सुरक्षित है: रेंडर कैश बगल में स्थित है
परियोजना फ़ाइल, किसी होम निर्देशिका में नहीं, इसलिए पुन: चलाने पर **फिर से शुरू** होगा, न कि
पुस्तक को फिर से संश्लेषित करना।

<details>
<summary>Container details — tags, the cache, and file ownership</summary>

- `latest`, `3`, `3.0` और सटीक संस्करण के साथ टैग किया गया, प्रत्येक पर जीएचसीआर पर प्रकाशित किया गया
रिलीज़।
- एंट्रीपॉइंट **`audiobooker`** है, इसलिए छवि नाम के ठीक बाद सबकमांड पास करें - प्रोग्राम नाम को दोहराएं नहीं।
- कैश `<book-dir>/.audiobooker/cache` पर स्थित है। यही कारण है कि एक बाइंड माउंट निरंतरता को कवर करता है; इसे खोने का मतलब है कि पूरे टीटीएस रन के लिए फिर से भुगतान करना होगा, न कि केवल पुन: मल्टीप्लेक्सिंग करना।
- `/ext` एक वैकल्पिक दूसरा माउंट है, केवल आपके स्वयं के टीटीएस व्हील की आपूर्ति करने के लिए।
- कंटेनर एक गैर-रूट यूआईडी 1000 के रूप में चलता है। लिनक्स पर, यदि माउंट की गई
निर्देशिका उस यूआईडी द्वारा लिखने योग्य नहीं है, तो कैश नहीं लिखा जा सकता है - `--user "$(id -u):$(id -g)"` या `chown` निर्देशिका जोड़ें। डॉकर डेस्कटॉप पर
मैकओएस और विंडोज आपके लिए यह संभालता है।

</details>

**ऑडियो रेंडरिंग** को [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) टीटीएस इंजन (अतिरिक्त `[render]`) और पथ पर **एफएफएमपीईजी** (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`) की आवश्यकता होती है। रेंडर तक सब कुछ - पार्स, कास्ट, कंपाइल, समीक्षा - इसके बिना काम करता है। अपने सेटअप की जांच करने के लिए `audiobooker diagnose` चलाएं।

<details>
<summary>From source</summary>

```bash
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e '.[render]'
```
</details>

<details>
<summary><strong>Upgrading from 2.x</strong> — five things changed on purpose</summary>

इनमें से प्रत्येक एक ऐसा मामला है जहां 2.x ने कुछ स्वीकार किया और चुपचाप गलत काम किया। 3.0 इसके बजाय मना कर देता है। पूरी जानकारी [चेंजलॉग](CHANGELOG.md) में।

- **आपकी पहली रेंडरिंग हर अध्याय को एक बार फिर से रेंडर करती है।** तीन इनपुट जो
ऑडियो को बदलते हैं - भावना प्रीसेट, उच्चारण तीव्रता, प्रति-चरित्र
गति/पिच/जोर - कैश कुंजी से गायब थे, इसलिए प्रीसेट बदलने पर "कैश्ड" रिपोर्ट किया गया और पुरानी ऑडियो वापस कर दी गई। वे अब कुंजी में हैं, और
2.x कैश प्रविष्टि यह साबित नहीं कर सकती है कि इसने इसे कैसे उत्पन्न किया।
- **`--format m4a` अब पूरे पुस्तक विकल्प नहीं है।** इसका मतलब हमेशा प्रति अध्याय एक फ़ाइल होता था; `m4a` में पूरी पुस्तक के लिए पूछने से पहले एक
एकल एम4बी एक `.m4a` नाम के तहत उत्पन्न हुआ। यह अभी भी `podcast --format` पर मान्य है।
- **`render` उस पुस्तक को अस्वीकार करता है जिसके एट्रिब्यूशन में `FAILED` लिखा है** बजाय इसके कि
इसके लिए टीटीएस रन खर्च किया जाए। `--force` ओवरराइड करता है। `audiobooker report` चलाएं यह देखने के लिए कि यह किन पंक्तियों पर आपत्ति कर रहा है।
- **`make` तब अस्वीकार करता है जब परियोजना फ़ाइल पहले से मौजूद है।** इसने पहले
हाथ से डाली गई आवाजों, उच्चारण ओवरराइड और संपादित शीर्षकों को एक ताज़ा ऑटो-कास्ट पार्स से बदल दिया। यदि यही आप चाहते हैं तो `--overwrite-project` पास करें।
- **`compile()` तब त्रुटि उत्पन्न करता है जब प्रत्येक अध्याय विफल हो जाता है** बजाय `None` वापस करने के
जिस तरह से एक स्वच्छ रन करता है। यदि आप इसे पायथन से कॉल करते हैं, तो यह अब त्रुटि उत्पन्न कर सकता है।

</details>

## त्वरित शुरुआत

```bash
# One command: parse -> auto-cast -> compile -> render -> master
audiobooker make mybook.epub --acx

# ...or the staged workflow, with control at each step:
audiobooker new mybook.epub            # parse into chapters (EPUB/PDF/TXT/MD/DOCX, or a folder)
audiobooker cast --interactive         # guided per-character casting
audiobooker audition Sarah --render    # A/B candidate voices for one character
audiobooker compile                    # detect dialogue, attribute speakers, infer emotion
audiobooker report                     # what's weak? unattributed + guessed rates, top lines
audiobooker review-export              # human-editable script — fix attributions
audiobooker review-import mybook_review.txt
audiobooker render --acx               # render + master to ACX spec
audiobooker master-check mybook.m4b    # PASS/FAIL vs ACX loudness/peak/noise-floor
```

## विशेषताएं

### इनपुट और संरचना
- **ईपीयूबी, टीएक्सटी, मार्कडाउन, पीडीएफ, डीओएक्स**, या **प्रति-अध्याय फ़ाइलों का एक फ़ोल्डर** (स्क्रिवनर/ओब्सीडियन/क्रमिक उपन्यास)।
- **टीओसी-संचालित ईपीयूबी विभाजन** - पुस्तक की अपनी तालिका सामग्री से अध्याय सीमाएं और शीर्षक।
- **डीओएक्स** वर्ड `Heading 1/2`/`Title` शैलियों पर विभाजित होता है; **पीडीएफ** शीर्षकों का पता लगाता है (स्कैन किए गए पीडीएफ गार्ड के साथ); कस्टम `--chapter-delimiter`।
- स्मार्ट टेक्स्ट क्लीनिंग, मार्कडाउन-जागरूक स्ट्रिपिंग, पाद लेख हैंडलिंग, और एक **पुन: प्रयोज्य उच्चारण लेक्सिकॉन** (`pronunciation import/export`, सीएसवी/जेएसओएन, जिसमें फोनम पासथ्रू शामिल है)।

### कास्टिंग और एट्रिब्यूशन
- **बहु-आवाज संश्लेषण** जिसमें व्याख्या योग्य, रैंक की गई आवाज **सुझाव** और प्रति पात्र उम्मीदवारों को ए/बी करने के लिए एक **`audition`** कमांड शामिल है।
- **इंटरैक्टिव कास्टिंग**, लिंग/भूमिका द्वारा **बल्क `cast-fill`**, श्रृंखला में पुन: प्रयोज्य **नाम वाली कास्ट प्रीसेट**, और सहयोगियों के लिए **सीएसवी कास्ट शीट**।
- **संवाद का पता लगाना + स्पीकर एट्रिब्यूशन** (वैकल्पिक **बुकएनएलपी** सह-संदर्भ), **उपनाम ऑटो-डिस्कवरी**, और समायोज्य **तीव्रता**, **दृश्य-स्तर के मूड** और शैली **प्रीसेट पैक** के साथ **भावना अनुमान**।
- **एट्रिब्यूशन जिसे आप ऑडिट कर सकते हैं।** प्रत्येक पंक्ति रिकॉर्ड करती है कि इसके स्पीकर का निर्णय कैसे लिया गया - एक भाषण टैग, एक इनलाइन ओवरराइड, सह-संदर्भ, आपका स्वयं का सुधार, या एक साधारण वैकल्पिक-बारी का अनुमान - और `report` उन अनुमानों को अलग से गिनता है जिनसे वह बिल्कुल भी एट्रिब्यूट नहीं कर सका। एक अनुमान स्कोर में सुधार नहीं कर सकता है, इसलिए जब एट्रिब्यूशन बदतर हो जाता है तो संख्या कम हो जाती है, जो एकमात्र दिशा है जो उपयोगी है।

### रेंडरिंग और आउटपुट
- **एम4बी** (अध्याय मार्कर + एम्बेडेड कवर + श्रृंखला मेटाडेटा), **एमपी3**, **ओपस**, **एफएलएसी**, **डब्ल्यूएवी**; प्रति-अध्याय निर्यात; **पॉडकास्ट/आरएसएस** फ़ीड निर्यात।
डब्ल्यूएवी में कोई अध्याय परमाणु नहीं है, इसलिए डब्ल्यूएवी रेंडर स्पष्ट रूप से कहता है कि ऐसा है, न कि विफल अध्याय मल्टीप्लेक्स की रिपोर्ट करता है - इसका उपयोग करें जब ऑडियो एक संपादक में जा रहा हो।
- **एसीएक्स-विशिष्ट मास्टरींग** (`--acx`) + एक **`master-check`** जो आरएमएस लाउडनेस, पीक और शोर फर्श पर पास/असफल की रिपोर्ट करता है; खुदरा **`sample`** क्लिप।
- समानांतर रेंडरिंग, एक **निरंतर रेंडर कैश** जिसमें फिर से शुरू करने की सुविधा है, गतिशील प्रगति + ईटीए, और संरचित विफलता रिपोर्ट।
कैश कुंजी उन सभी चीजों को कवर करती है जो ऑडियो को बदलती हैं - पाठ, कास्ट, आवाजें, इंजन और संस्करण, प्रोफ़ाइल, भावना प्रीसेट और तीव्रता - इसलिए एक पुन: रेंडर जो "कैश्ड" कहता है, इसका मतलब है। एक वैकल्पिक **प्रति-उच्चारण कैश** (`utterance_cache`) एक पुन: रेंडर को उन पंक्तियों तक सीमित करता है जिन्हें आपने वास्तव में संपादित किया है।

### कार्यप्रवाह और पारिस्थितिकी तंत्र
- **`make`** वन-शॉट पाइपलाइन · **कॉन्फ़िगरेशन फ़ाइल** (`.audiobookerrc` / `[tool.audiobooker]`) · **`--watch`** मोड · **मैनिफेस्ट-संचालित बैच** · शेल पूर्णता।
- **7 भाषा प्रोफ़ाइल** (en/fr/de/es/ja/it/pt) · **प्लग करने योग्य टीटीएस इंजन** (`--engine`, एंट्रीपॉइंट - पाइपर/कोकी/एलेवनलैब्स लाएं) · अधिकांश कमांड पर स्क्रिप्टेबल `--json` · संरचित निकास कोड।

## एसीएक्स ऑडियो विनिर्देश के अनुसार मास्टरींग

ACX एक सटीक, मापने योग्य ऑडियो लक्ष्य प्रकाशित करता है। यह ऑडियोबुक दुनिया के लिए एक मानकीकृत मानदंड के सबसे करीब है, और फ़ाइल के साथ आप जो भी करते हैं, उसके बाद इसे पूरा करना सार्थक है।

| आवश्यकता | ACX विनिर्देश | `--acx` क्या करता है |
|---|---|---|
| ध्वनि स्तर | **−23 और −18 dBFS** के बीच RMS | −20 LUFS पर दो-पास `loudnorm`, जो भाषण के लिए उस सीमा के भीतर आता है |
| पीक | **−3 dBFS** पर या उससे नीचे | उसी प्रक्रिया में लागू किया गया |
| शोर स्तर | **−60 dBFS** पर या उससे नीचे | मापा और रिपोर्ट किया गया — कभी भी चुपचाप "ठीक" नहीं किया गया |
| प्रारूप | **44.1 kHz, 192 kbps CBR MP3** | सैंपल दर निर्धारित करता है; कोडेक के लिए `--format mp3 --bitrate 192k` जोड़ें |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

ऊपर दिए गए नंबरों के लिए दो बातें:

**`master-check` भारित RMS को मापता है, LUFS नहीं।** वे अलग-अलग मात्राएँ हैं और ACX बाद वाले पर प्रतिबंध लगाता है। −20 LUFS आंकड़ा यह है कि मानकीकरण प्रक्रिया *कैसे* वहां पहुंचती है — यह वह है जिसे `ffmpeg loudnorm` लक्षित कर सकता है — न कि बाद में क्या जांचा जाता है।

**शोर स्तर को मापा जाता है, ठीक नहीं किया जाता है।** यह वह आवश्यकता है जो सबसे अधिक विफल होती है, और यह स्रोत ऑडियो से आती है। एक उपकरण जो इसे चुपचाप सीमित करता है, वह उस एक संख्या को छिपा देगा जिसे आपको देखने की आवश्यकता है।

### जहां एक AI- द्वारा सुनाई गई ऑडियोबुक वास्तव में जा सकती है

विशिष्टताओं को पूरा करना, स्वीकार किए जाने के समान नहीं है, और यह स्पष्ट करने योग्य है: **ACX का मानक सबमिशन प्रवाह मानव कथन के लिए है।** इसकी अप्रैल 2026 आवश्यकताओं की सूची में अनधिकृत टेक्स्ट-टू-स्पीच और AI रिकॉर्डिंग शामिल हैं, जिन्हें यह स्वीकार नहीं करता है, इसलिए एक AI- द्वारा सुनाई गई शीर्षक को सामान्य सबमिशन के बजाय ACX से पूर्व प्राधिकरण की आवश्यकता होती है।

वे मार्ग जो AI कथन को स्वीकार करते हैं, आमतौर पर प्रकटीकरण के साथ, उनमें Amazon का **Virtual Voice** (KDP के माध्यम से, केवल Amazon वितरण) और **Spotify Audiobooks for Authors**, **Author's Republic** और **Kobo Writing Life** जैसे एग्रीगेटर शामिल हैं। इस क्षेत्र में खुदरा नीति तेजी से बदलती है — इस पैराग्राफ पर भरोसा करने के बजाय वर्तमान नियमों की स्वयं जांच करें।

इसलिए: `--acx` ऑडियो के बारे में है। चाहे कोई खुदरा विक्रेता AI- द्वारा सुनाई गई शीर्षक को स्वीकार करता है या नहीं, यह उनका निर्णय है, न कि आपके द्वारा बनाई गई फ़ाइल का गुण।

## CLI कमांड

| कमांड | विवरण |
|---------|-------------|
| `make <file>` | एक बार में: नया → संकलित करें → ऑटो-कास्ट → रेंडर करें |
| `new <फ़ाइल\ | फ़ोल्डर>` | EPUB/TXT/MD/PDF/DOCX या किसी फ़ोल्डर से एक प्रोजेक्ट बनाएं |
| `from-stdin` | पाइप्ड टेक्स्ट से एक प्रोजेक्ट बनाएं |
| `cast <char> <voice>` · `cast-interactive` | आवाजें असाइन करें (या निर्देशित प्रति-वक्ता कास्टिंग; साथ ही `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | आवाजें सुझाएं / स्वचालित रूप से लागू करें / बल्क में असाइन करें |
| `cast-preset save\ | list\ | apply\ | delete` | पुस्तकों में पुन: प्रयोज्य कास्ट प्रीसेट |
| `cast-export` · `cast-import <file>` | कास्ट को JSON/CSV के रूप में राउंड-ट्रिप करें — हाथ से संपादित करें, या संस्करणों में पुन: उपयोग करें |
| `audition <char>` | एक चरित्र (`--render`) के लिए A/B रैंक किए गए उम्मीदवार आवाजें |
| `compile` | संवाद का पता लगाएं, वक्ताओं को विशेषता दें, भावना का अनुमान लगाएं |
| `report` | संकलन गुणवत्ता: गैर-विशेषीकृत दर, अनुमानित दर, सबसे खराब पंक्तियाँ, भावना मिश्रण |
| `review-export` · `review-import <file>` | मानव-संपादित समीक्षा राउंड-ट्रिप |
| `render` | ऑडियोबुक रेंडर करें (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`) |
| `sample` · `master-check <file>` | मानकीकृत खुदरा नमूना · ACX ऑडियो विनिर्देश के विरुद्ध जांच करें |
| `export-chapters` · `podcast` | अध्याय क्यू शीट (ffmetadata/cue/json) · पॉडकास्ट RSS फ़ीड |
| `preview` · `batch` · `diagnose` | वॉइस QA क्लिप · बैच/`--manifest` · पर्यावरण जांच (जब बॉक्स रेंडर नहीं कर सकता तो गैर-शून्य से बाहर निकलें) |
| `load <file>` | एक मौजूदा `.audiobooker` प्रोजेक्ट खोलें |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | निरीक्षण और प्रबंधित करें |

प्रत्येक कमांड `-h/--help` का समर्थन करता है। वैश्विक ध्वज: `--silent`, `--debug`। **निकास कोड:** `0` ठीक · `1` उपयोगकर्ता त्रुटि (जिसमें एक ऐसी पुस्तक भी शामिल है जो संकलित नहीं होगी, या एक रेंडर अस्वीकार कर दिया गया क्योंकि विशेषता विफल हो गई) · `2` रनटाइम · `3` आंशिक (बैच)।

## कॉन्फ़िगरेशन

एक बार डिफ़ॉल्ट सेट करें, ध्वजों को बार-बार पास करने के बजाय — `.audiobookerrc` (TOML) अपनी पुस्तक के बगल में, या `[tool.audiobooker]` में `pyproject.toml`। प्राथमिकता है **CLI ध्वज > प्रोजेक्ट कॉन्फ़िगरेशन > उपयोगकर्ता कॉन्फ़िगरेशन (`~/.audiobookerrc`) > अंतर्निहित डिफ़ॉल्ट।**

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## प्लग करने योग्य TTS इंजन

डिफ़ॉल्ट इंजन `voice-soundboard` है, लेकिन संश्लेषण बैकएंड को सेटटूल एंट्री-पॉइंट्स (`audiobooker.tts_engines`) के माध्यम से बदला जा सकता है:

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

एक प्लगइन (`pip install audiobooker-piper`) स्वयं को पंजीकृत करता है; किसी फोर्क की आवश्यकता नहीं है।

## पायथन API

```python
from audiobooker import AudiobookProject

project = AudiobookProject.from_epub("mybook.epub")   # or from_docx / from_pdf / from_folder / from_string
project.cast("narrator", "bm_george", emotion="calm")
project.cast("Alice", "af_bella", emotion="warm")
project.compile()                                     # dialogue, speakers, emotion
project.render("mybook.m4b")                          # resumes from cache on re-run
project.save("mybook.audiobooker")
```

`render(...)` और `compile(...)` एक इंजेक्ट किए गए `engine=` (किसी भी ऑब्जेक्ट को लागू करने वाले `TTSEngine` प्रोटोकॉल) और एक प्रगति कॉलबैक को स्वीकार करते हैं — GUI या सेवा में ऑडियोबुकर को एम्बेड करें।

## आर्किटेक्चर

```
audiobooker/
├── parser/      # EPUB, PDF, TXT/MD, DOCX, folder, language-aware splitting
├── language/    # 7 language profiles (quotes, speaker verbs, chapter patterns)
├── casting/     # dialogue detection, voice suggestion, presets, cast-fill
├── nlp/         # BookNLP adapter, emotion inference, speaker/alias resolution
├── renderer/    # synthesis, chapter+utterance cache, mastering, assembly, RSS
├── config_file.py · review.py · project.py · cli.py
```

```
Source (EPUB/PDF/DOCX/TXT/folder) -> Parser -> Chapters -> Dialogue & Emotion ->
Casting -> Review/Edit -> TTS (pluggable) -> cached audio -> FFmpeg master -> M4B/MP3/Opus/FLAC/WAV
```

## सुरक्षा और डेटा दायरा

- **नेटवर्क:** कोई नहीं — कोई टेलीमेट्री नहीं, कोई डेटा संग्रहण नहीं, कोई क्रेडेंशियल नहीं। आपकी पुस्तक फ़ाइलों को पढ़ता है, ऑडियो + कैश को आपके आउटपुट निर्देशिकाओं में लिखता है।
- **अनुमतियाँ:** इनपुट तक पढ़ने की पहुंच, आउटपुट तक लिखने की पहुंच; वैकल्पिक FFmpeg + PATH पर एक TTS इंजन।
- [SECURITY.md](SECURITY.md) देखें।

## स्कोरकार्ड

| गेट | स्थिति |
|------|--------|
| A. सुरक्षा आधारभूत | पास |
| B. त्रुटि प्रबंधन | पास |
| C. ऑपरेटर दस्तावेज़ | पास |
| D. शिपिंग स्वच्छता | पास |
| E. पहचान | पास |

## लाइसेंस

[MIT](LICENSE)

---

MCP Tool Shop द्वारा निर्मित <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
