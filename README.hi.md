<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.ja.md">日本語</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.zh.md">中文</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.es.md">Español</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.fr.md">Français</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.hi.md">हिन्दी</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.it.md">Italiano</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/audiobooker/main/assets/audiobooker-logo.png" alt="Audiobooker" width="500" />
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

ऑडियोबुकर संवाद का पता लगाता है, प्रत्येक पात्र को एक विशिष्ट आवाज देता है, भावनाओं का अनुमान लगाता है, आपको एक भी सेकंड रेंडर होने से पहले सब कुछ समीक्षा और सही करने देता है, फिर परिणाम को ACX ऑडियो विनिर्देश के अनुसार अनुकूलित करता है - इसलिए आउटपुट एक *तैयार* ऑडियोबुक है, न कि केवल जेनरेट की गई ऑडियो।

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

**डॉकर** - एफएफएमपीईजी पहले से ही इसमें है, प्रत्येक रिलीज़ पर जीएचसीआर पर प्रकाशित:
```bash
docker run --rm -v "$(pwd):/data" ghcr.io/mcp-tool-shop-org/audiobooker \
  make /data/mybook.epub --acx
```
यह एक माउंट पर्याप्त है, और `--rm` सुरक्षित है: रेंडर कैश बगल में स्थित है
परियोजना फ़ाइल, होम निर्देशिका में नहीं, इसलिए पुन: चलाने पर **पुन: शुरू** होता है
पुस्तक को फिर से संश्लेषित करने के बजाय।

<details>
<summary>Container details — tags, the cache, and file ownership</summary>

- `latest`, `2`, `2.1` और सटीक संस्करण के साथ टैग किया गया, प्रत्येक पर जीएचसीआर पर प्रकाशित
रिलीज़।
- एंट्रीपॉइंट **`audiobooker`** है, इसलिए छवि नाम के ठीक बाद सबकमांड पास करें - प्रोग्राम नाम को दोहराएं नहीं।
- कैश `<book-dir>/.audiobooker/cache` पर उतरता है। यही कारण है कि एक बाइंड माउंट निरंतरता को कवर करता है; इसे खोने का मतलब है कि पूरे टीटीएस रन के लिए फिर से भुगतान करना होगा, न कि केवल पुन: मल्टीप्लेक्सिंग करना।
- `/ext` एक वैकल्पिक दूसरा माउंट है, केवल आपके स्वयं के टीटीएस व्हील की आपूर्ति करने के लिए।
- कंटेनर एक गैर-रूट यूआईडी 1000 के रूप में चलता है। लिनक्स पर, यदि माउंट की गई निर्देशिका उस यूआईडी द्वारा लिखने योग्य नहीं है, तो कैश नहीं लिखा जा सकता है - `--user "$(id -u):$(id -g)"` या `chown` निर्देशिका जोड़ें। डॉकर डेस्कटॉप पर
मैकओएस और विंडोज आपके लिए इसे संभालता है।

</details>

**ऑडियो रेंडरिंग** को [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) टीटीएस इंजन (अतिरिक्त `[render]`) और पीएटीएच पर **एफएफएमपीईजी** (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`) की आवश्यकता होती है। रेंडर तक सब कुछ - पार्स, कास्ट, कंपाइल, समीक्षा - बिना उनके काम करता है। अपने सेटअप की जांच करने के लिए `audiobooker diagnose` चलाएं।

<details>
<summary>From source</summary>

```bash
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e '.[render]'
```
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
audiobooker report                     # what's weak? unknown-attribution rate + top lines
audiobooker review-export              # human-editable script — fix attributions
audiobooker review-import mybook_review.txt
audiobooker render --acx               # render + master to ACX spec
audiobooker master-check mybook.m4b    # PASS/FAIL vs ACX loudness/peak/noise-floor
```

## विशेषताएं

### इनपुट और संरचना
- **ईपीयूबी, टीएक्सटी, मार्कडाउन, पीडीएफ, डीओसीएक्स**, या **प्रति-अध्याय फ़ाइलों का एक फ़ोल्डर** (स्क्रिवनर/ओब्सीडियन/क्रमबद्ध फिक्शन)।
- **टीओसी-संचालित ईपीयूबी विभाजन** - पुस्तक की अपनी सामग्री तालिका से अध्याय सीमाएं और शीर्षक।
- **डीओसीएक्स** वर्ड `Heading 1/2`/`Title` शैलियों पर विभाजित होता है; **पीडीएफ** शीर्षकों का पता लगाता है (स्कैन किए गए पीडीएफ गार्ड के साथ); कस्टम `--chapter-delimiter`।
- स्मार्ट टेक्स्ट क्लीनिंग, मार्कडाउन-जागरूक स्ट्रिपिंग, पाद लेख हैंडलिंग, और एक **पुन: प्रयोज्य उच्चारण लेक्सिकॉन** (`pronunciation import/export`, सीएसवी/जेएसओएन, जिसमें फोनिम पासथ्रू है)।

### कास्टिंग और विशेषता
- **बहु-आवाज संश्लेषण** जिसमें व्याख्या योग्य, रैंक की गई आवाज **सुझाव** और प्रति पात्र उम्मीदवारों को ए/बी करने के लिए एक **`audition`** कमांड शामिल है।
- **इंटरैक्टिव कास्टिंग**, लिंग/भूमिका द्वारा **बल्क `cast-fill`**, श्रृंखला में पुन: प्रयोज्य **नाममात्र कास्ट प्रीसेट**, और सहयोगियों के लिए **सीएसवी कास्ट शीट**।
- **संवाद का पता लगाना + स्पीकर विशेषता** (वैकल्पिक **बुकएनएलपी** सह-संदर्भ), **उपनाम ऑटो-डिस्कवरी**, और समायोज्य **तीव्रता**, **दृश्य-स्तर के मूड** और शैली **प्रीसेट पैक** के साथ **भावना अनुमान**।

### रेंडरिंग और आउटपुट
- **एम4बी** (अध्याय मार्कर + एम्बेडेड कवर + श्रृंखला मेटाडेटा), **एमपी3**, **ओपस**, **एफएलएसी**, **डब्ल्यूएवी**; प्रति-अध्याय निर्यात; **पॉडकास्ट/आरएसएस** फ़ीड निर्यात।
डब्ल्यूएवी में कोई अध्याय परमाणु नहीं है, इसलिए डब्ल्यूएवी रेंडर स्पष्ट रूप से ऐसा कहता है, बजाय विफल अध्याय मल्टीप्लेक्स की रिपोर्ट करने के - इसका उपयोग तब करें जब ऑडियो किसी संपादक में जा रहा हो।
- **एसीएक्स-विशिष्ट मास्टरी** (`--acx`) + एक **`master-check`** जो आरएमएस लाउडनेस, पीक और शोर तल पर पास/फेल की रिपोर्ट करता है; खुदरा **`sample`** क्लिप।
- समानांतर रेंडरिंग, एक **निरंतर रेंडर कैश** जिसमें फिर से शुरू करने की क्षमता, गतिशील प्रगति + ईटीए और संरचित विफलता रिपोर्ट शामिल हैं।

### कार्यप्रवाह और पारिस्थितिकी तंत्र
- **`make`** वन-शॉट पाइपलाइन · **कॉन्फ़िगरेशन फ़ाइल** (`.audiobookerrc` / `[tool.audiobooker]`) · **`--watch`** मोड · **मैनिफेस्ट-संचालित बैच** · शेल पूर्णता।
- **7 भाषा प्रोफाइल** (en/fr/de/es/ja/it/pt) · **प्लग करने योग्य टीटीएस इंजन** (`--engine`, एंट्री-पॉइंट - पाइपर/कोकी/एलेवनलैब्स लाएं) · अधिकांश कमांड पर स्क्रिप्टेबल `--json` · संरचित निकास कोड।

## एसीएक्स ऑडियो विनिर्देश के अनुसार मास्टरी

एसीएक्स एक सटीक, मापने योग्य ऑडियो लक्ष्य प्रकाशित करता है। यह ऑडियोबुक दुनिया में मास्टरी मानक के सबसे करीब है, और यह इसके लायक है कि आप फ़ाइल के साथ जो भी करते हैं, उसे प्राप्त करें।

| आवश्यकता | एसीएक्स विनिर्देश | `--acx` क्या करता है |
|---|---|---|
| लाउडनेस | **−23 और −18 डीबीएफएस** के बीच आरएमएस | -20 एलयूएफएस पर दो-पास `loudnorm`, जो उस विंडो के अंदर आता है। |
| पीक | **−3 डीबीएफएस** पर या उससे नीचे | उसी पास में लागू किया गया |
| शोर तल | **−60 डीबीएफएस** पर या उससे नीचे | मापा और रिपोर्ट किया गया - चुपचाप "ठीक" नहीं किया गया |
| प्रारूप | **44.1 kHz, 192 kbps CBR MP3** | सैंपल दर सेट करता है; कोडेक के लिए `--format mp3 --bitrate 192k` जोड़ें |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

ऊपर दिए गए नंबरों के लिए दो बातें:

**`master-check` बिना भारित आरएमएस को मापता है, एलयूएफएस नहीं।** वे अलग-अलग मात्राएं हैं और एसीएक्स पूर्व पर गेट करता है। -20 एलयूएफएस आंकड़ा यह है कि मास्टरी पास *इसे कैसे प्राप्त करता है* - यह वह है जिसे `ffmpeg loudnorm` लक्षित कर सकता है - न कि बाद में क्या जांचा जाता है।

**शोर तल को मापा जाता है, ठीक नहीं किया जाता है।** यह सबसे अधिक विफल होने वाली आवश्यकता है, और यह स्रोत ऑडियो से आती है। एक उपकरण जो इसे चुपचाप गेट करता है, वह उस एक नंबर को छिपा देगा जिसे आपको देखने की आवश्यकता है।

### जहां एक एआई-वर्णित ऑडियोबुक वास्तव में जा सकती है

विशिष्टताओं को पूरा करना स्वीकार किए जाने के समान नहीं है, और यह स्पष्ट होना लायक है: **एसीएक्स का मानक सबमिशन प्रवाह मानव कथन के लिए है।** इसकी अप्रैल 2026 आवश्यकताओं की सूची में अनधिकृत टेक्स्ट-टू-स्पीच और एआई रिकॉर्डिंग शामिल हैं, जो उन चीजों में से हैं जिन्हें यह स्वीकार नहीं करता है, इसलिए एक एआई-वर्णित शीर्षक को एसीएक्स से पूर्व प्राधिकरण की आवश्यकता होती है, न कि एक सामान्य सबमिशन।

वे मार्ग जो एआई कथन को स्वीकार करते हैं, उनमें आमतौर पर प्रकटीकरण शामिल होता है, जैसे कि:
अमेज़ॅन का **वर्चुअल वॉयस**, जो केडीपी (केवल अमेज़ॅन वितरण) के माध्यम से उपलब्ध है, और
**स्पॉटिफाई ऑडियोबुक्स फॉर ऑथर्स**, **ऑथर्स रिपब्लिक** और **कोबो राइटिंग लाइफ** जैसे एग्रीगेटर। इस क्षेत्र में खुदरा नीति तेजी से बदलती है - इस पैराग्राफ पर भरोसा करने के बजाय, वर्तमान नियमों की स्वयं जांच करें।

इसलिए: `--acx` ऑडियो के बारे में है। क्या कोई खुदरा विक्रेता एआई-कथन वाली सामग्री को स्वीकार करता है, यह उनका निर्णय है, न कि आपके द्वारा बनाई गई फ़ाइल का गुण।

## सीएलआई कमांड

| कमांड | विवरण |
|---------|-------------|
| `make <file>` | एक बार में: नया → संकलित करें → ऑटो-कास्ट → रेंडर करें |
| `new <फ़ाइल\ | फ़ोल्डर>` | ईपीयूबी/टीएक्सटी/एमडी/पीडीएफ/डीओसीएक्स या किसी फ़ोल्डर से एक प्रोजेक्ट बनाएं |
| `from-stdin` | पाइप्ड टेक्स्ट से एक प्रोजेक्ट बनाएं |
| `cast <char> <voice>` · `cast-interactive` | आवाजें असाइन करें (या निर्देशित प्रति-वक्ता कास्टिंग; साथ ही `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | आवाजें सुझाएं / स्वचालित रूप से लागू करें / बड़ी संख्या में असाइन करें |
| `cast-preset save\ | list\ | apply\ | delete` | पुस्तकों में पुन: प्रयोज्य कास्ट प्रीसेट |
| `cast-export` · `cast-import <file>` | कास्ट को JSON/CSV के रूप में राउंड-ट्रिप करें - मैन्युअल रूप से संपादित करें, या विभिन्न संस्करणों में पुन: उपयोग करें |
| `audition <char>` | एक चरित्र के लिए ए/बी रैंक वाली उम्मीदवार आवाजें (`--render`) |
| `compile` | संवाद का पता लगाएं, वक्ताओं को विशेषता दें, भावनाओं का अनुमान लगाएं |
| `report` | संकलन गुणवत्ता: अज्ञात दर, शीर्ष गैर-एट्रीब्यूटेड लाइनें, भावना मिश्रण |
| `review-export` · `review-import <file>` | मानव-संपादित समीक्षा राउंड-ट्रिप |
| `render` | ऑडियोबुक रेंडर करें (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`) |
| `sample` · `master-check <file>` | मास्टर किया गया खुदरा नमूना · एसीएक्स ऑडियो विनिर्देश के विरुद्ध जांच करें |
| `export-chapters` · `podcast` | अध्याय क्यू शीट (ffmetadata/cue/json) · पॉडकास्ट आरएसएस फ़ीड |
| `preview` · `batch` · `diagnose` | वॉइस क्यूए क्लिप · बैच/`--manifest` · पर्यावरण जांच (यदि बॉक्स रेंडर नहीं कर सकता है तो गैर-शून्य मान के साथ बाहर निकलें) |
| `load <file>` | एक मौजूदा `.audiobooker` प्रोजेक्ट खोलें |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | निरीक्षण और प्रबंधन करें |

प्रत्येक कमांड `-h/--help` का समर्थन करता है। वैश्विक ध्वज: `--silent`, `--debug`। **निकास कोड:** `0` ठीक · `1` उपयोगकर्ता त्रुटि (जिसमें एक ऐसी पुस्तक भी शामिल है जो संकलित नहीं होगी, या एक रेंडर जो अस्वीकार कर दिया गया क्योंकि विशेषता विफल हो गई) · `2` रनटाइम · `3` आंशिक (बैच)।

## कॉन्फ़िगरेशन

बार-बार ध्वज पास करने के बजाय एक बार डिफ़ॉल्ट सेट करें - `.audiobookerrc` (टीओएमएल) आपकी पुस्तक के बगल में, या `[tool.audiobooker]` में `pyproject.toml`। प्राथमिकता है: **सीएलआई ध्वज > प्रोजेक्ट कॉन्फ़िगरेशन > उपयोगकर्ता कॉन्फ़िगरेशन (`~/.audiobookerrc`) > अंतर्निहित डिफ़ॉल्ट**।

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## प्लग करने योग्य टीटीएस इंजन

डिफ़ॉल्ट इंजन `voice-soundboard` है, लेकिन संश्लेषण बैकएंड को सेटuptools एंट्री-पॉइंट्स (`audiobooker.tts_engines`) के माध्यम से बदला जा सकता है:

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

एक प्लगइन (`pip install audiobooker-piper`) स्वयं को पंजीकृत करता है; किसी फोर्क की आवश्यकता नहीं है।

## पायथन एपीआई

```python
from audiobooker import AudiobookProject

project = AudiobookProject.from_epub("mybook.epub")   # or from_docx / from_pdf / from_folder / from_string
project.cast("narrator", "bm_george", emotion="calm")
project.cast("Alice", "af_bella", emotion="warm")
project.compile()                                     # dialogue, speakers, emotion
project.render("mybook.m4b")                          # resumes from cache on re-run
project.save("mybook.audiobooker")
```

`render(...)` और `compile(...)` एक इंजेक्ट किए गए `engine=` (किसी भी ऑब्जेक्ट को जो `TTSEngine` प्रोटोकॉल को लागू करता है) और एक प्रगति कॉलबैक स्वीकार करते हैं - ऑडियोबुकर को एक जीयूआई या सेवा में एम्बेड करें।

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

- **नेटवर्क:** कोई नहीं - कोई टेलीमेट्री नहीं, कोई डेटा संग्रहण नहीं, कोई क्रेडेंशियल नहीं। आपकी पुस्तक फ़ाइलों को पढ़ता है, ऑडियो + कैश को आपके आउटपुट निर्देशिकाओं में लिखता है।
- **अनुमतियाँ:** इनपुट तक पढ़ने की पहुंच, आउटपुट तक लिखने की पहुंच; वैकल्पिक एफएफmpeg + पाथ पर एक टीटीएस इंजन।
- [सुरक्षा.एमडी](SECURITY.md) देखें।

## स्कोरकार्ड

| गेट | स्थिति |
|------|--------|
| ए. सुरक्षा आधारभूत | पास |
| बी. त्रुटि प्रबंधन | पास |
| सी. ऑपरेटर दस्तावेज़ | पास |
| डी. शिपिंग स्वच्छता | पास |
| ई. पहचान | पास |

## लाइसेंस

[एमआईटी](LICENSE)

---

एमसीपी टूल शॉप द्वारा निर्मित <a href="https://mcp-tool-shop.github.io/">एमसीपी टूल शॉप</a>
