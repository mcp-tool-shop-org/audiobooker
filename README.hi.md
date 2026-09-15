<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.ja.md">日本語</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.zh.md">中文</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.es.md">Español</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.fr.md">Français</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.hi.md">हिन्दी</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.it.md">Italiano</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/mcp-tool-shop-org/audiobooker/main/assets/audiobooker-logo-dark.png">
    <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/audiobooker/main/assets/audiobooker-logo.png" alt="Audiobooker" width="500" />
  </picture>
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

**ऑडियो रेंडरिंग** के लिए [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) टीटीएस इंजन (अतिरिक्त `[render]`) और PATH पर **FFmpeg** (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`) की आवश्यकता होती है। रेंडर करने से पहले - पार्स, कास्ट, कंपाइल, समीक्षा - सब कुछ बिना इनके काम करता है। अपने सेटअप की जांच करने के लिए `audiobooker diagnose` चलाएं।

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
- **EPUB, TXT, Markdown, PDF, DOCX**, or a **folder of per-chapter files** (Scrivener/Obsidian/serialized fiction).
- **TOC-driven EPUB splitting** — chapter boundaries and titles from the book's own table of contents.
- **DOCX** splits on Word `Heading 1/2`/`Title` styles; **PDF** detects headings (with a scanned-PDF guard); custom `--chapter-delimiter`.
- Smart text cleaning, Markdown-aware stripping, footnote handling, and a **reusable pronunciation lexicon** (`pronunciation import/export`, CSV/JSON, with phoneme passthrough).

### कास्टिंग और विशेषता
- **बहु-आवाज संश्लेषण** जिसमें व्याख्या योग्य, रैंक की गई आवाज **सुझाव** और प्रति पात्र उम्मीदवारों के लिए एक **`audition`** कमांड शामिल है।
- **इंटरैक्टिव कास्टिंग**, लिंग/भूमिका के आधार पर **बल्क `cast-fill`**, श्रृंखला में पुन: प्रयोज्य **नाममात्र कास्ट प्रीसेट**, और सहयोगियों के लिए **सीएसवी कास्ट शीट**।
- **संवाद का पता लगाना + वक्ता विशेषता** (वैकल्पिक **बुकएनएलपी** सह-संदर्भ), **उपनाम ऑटो-डिस्कवरी**, और समायोज्य **तीव्रता**, **दृश्य-स्तरीय मनोदशा**, और शैली **प्रीसेट पैक** के साथ **भावना अनुमान**।

### रेंडरिंग और आउटपुट
- **एम4बी** (अध्याय मार्कर + एम्बेडेड कवर + श्रृंखला मेटाडेटा), **एमपी3**, **ओपस**, **एफएलएसी**, **डब्ल्यूएवी**; प्रति-अध्याय निर्यात; **पॉडकास्ट/आरएसएस** फ़ीड निर्यात।
डब्ल्यूएवी में कोई अध्याय एटम नहीं है, इसलिए डब्ल्यूएवी रेंडर स्पष्ट रूप से ऐसा बताता है, बजाय विफल अध्याय मक्स की रिपोर्ट करने के - जब ऑडियो किसी संपादक में जा रहा हो तो इसका उपयोग करें।
- **एसीएक्स-विशिष्ट मास्टरींग** (`--acx`) + एक **`master-check`** जो आरएमएस लाउडनेस, पीक और शोर स्तर पर पास/फेल की रिपोर्ट करता है; खुदरा **`sample`** क्लिप।
- समानांतर रेंडरिंग, एक **निरंतर रेंडर कैश** जिसमें फिर से शुरू करने की सुविधा, गतिशील प्रगति + ईटीए, और संरचित विफलता रिपोर्ट शामिल हैं।

### कार्यप्रवाह और पारिस्थितिकी तंत्र
- **`make`** वन-शॉट पाइपलाइन · **कॉन्फ़िगरेशन फ़ाइल** (`.audiobookerrc` / `[tool.audiobooker]`) · **`--watch`** मोड · **मैनिफेस्ट-संचालित बैच** · शेल पूर्णता।
- **7 भाषा प्रोफाइल** (en/fr/de/es/ja/it/pt) · **प्लग करने योग्य टीटीएस इंजन** (`--engine`, एंट्री-पॉइंट - पाइपर/कोकी/एलेवनलैब्स लाएं) · अधिकांश कमांड पर स्क्रिप्टेबल `--json` · संरचित निकास कोड।

## एसीएक्स ऑडियो विनिर्देश के अनुसार मास्टरींग

एसीएक्स एक सटीक, मापने योग्य ऑडियो लक्ष्य प्रकाशित करता है। यह ऑडियोबुक दुनिया में मास्टरींग मानक के सबसे करीब है, और यह इसके लायक है कि आप फ़ाइल के साथ आगे जो भी करें, उसे प्राप्त करें।

| आवश्यकता | एसीएक्स विनिर्देश | `--acx` क्या करता है |
|---|---|---|
| लाउडनेस | **−23 और −18 डीबीएफएस** के बीच आरएमएस | −20 एलयूएफएस पर दो-पास `loudnorm`, जो भाषण के लिए उस विंडो के अंदर आता है |
| पीक | **−3 डीबीएफएस** पर या उससे नीचे | उसी पास में लागू किया गया |
| शोर स्तर | **−60 डीबीएफएस** पर या उससे नीचे | मापा और रिपोर्ट किया गया - चुपचाप "ठीक" नहीं किया गया |
| प्रारूप | **44.1 kHz, 192 kbps CBR MP3** | सैंपल दर सेट करता है; कोडेक के लिए `--format mp3 --bitrate 192k` जोड़ें |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

ऊपर दिए गए नंबरों के लिए दो बातें:

**`master-check` अनवेटेड आरएमएस को मापता है, एलयूएफएस नहीं।** वे अलग-अलग मात्राएं हैं और एसीएक्स पूर्व पर गेट करता है। −20 एलयूएफएस आंकड़ा यह है कि मास्टरींग पास *इसे कैसे प्राप्त करता है* - यह वह है जिसे `ffmpeg loudnorm` लक्षित कर सकता है - न कि बाद में क्या जांचा जाता है।

**शोर स्तर को मापा जाता है, ठीक नहीं किया जाता है।** यह सबसे अधिक विफल होने वाली आवश्यकता है, और यह स्रोत ऑडियो से आती है। एक उपकरण जो इसे चुपचाप गेट करता है, वह उस एक नंबर को छिपा देगा जिसे आपको देखने की आवश्यकता है।

### जहां एआई-वर्णित ऑडियोबुक वास्तव में जा सकती है

विशिष्टताओं को पूरा करना स्वीकार किए जाने के समान नहीं है, और यह स्पष्ट करने योग्य है: **एसीएक्स का मानक सबमिशन प्रवाह मानव कथन के लिए है।** इसकी अप्रैल 2026 आवश्यकताओं की सूची में अनधिकृत टेक्स्ट-टू-स्पीच और एआई रिकॉर्डिंग शामिल हैं, जो उन चीजों में से हैं जिन्हें यह स्वीकार नहीं करता है, इसलिए एआई-वर्णित शीर्षक को एसीएक्स से पूर्व प्राधिकरण की आवश्यकता होती है, न कि सामान्य सबमिशन की।

वे मार्ग जो आमतौर पर प्रकटीकरण के साथ एआई कथन को स्वीकार करते हैं, उनमें अमेज़ॅन के **वर्चुअल वॉयस** के माध्यम से केडीपी (केवल अमेज़ॅन वितरण) और **स्पोटिफाई ऑडियोबुक्स फॉर ऑथर्स**, **ऑथर्स रिपब्लिक** और **कोबो राइटिंग लाइफ** जैसे एग्रीगेटर शामिल हैं। इस क्षेत्र में खुदरा नीति तेजी से बदलती है - इस पैराग्राफ पर भरोसा करने के बजाय वर्तमान नियमों की स्वयं जांच करें।

इसलिए: `--acx` ऑडियो के बारे में है। चाहे कोई खुदरा विक्रेता एआई-वर्णित शीर्षक को स्वीकार करता है या नहीं, यह उनका निर्णय है, न कि आपके द्वारा बनाए गए फ़ाइल का गुण।

## सीएलआई कमांड

| कमांड | विवरण |
|---------|-------------|
| `make <file>` | एक-शॉट: नया → संकलित करें → ऑटो-कास्ट → रेंडर करें |
| `new <फ़ाइल\ | फ़ोल्डर>` | ईपीयूबी/टीएक्सटी/एमडी/पीडीएफ/डीओसीएक्स या एक फ़ोल्डर से एक प्रोजेक्ट बनाएं |
| `from-stdin` | पाइप्ड टेक्स्ट से एक प्रोजेक्ट बनाएं |
| `cast <char> <voice>` · `cast-interactive` | आवाजें असाइन करें (या निर्देशित प्रति-वक्ता कास्टिंग; साथ ही `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | आवाजें सुझाएं / स्वचालित रूप से लागू करें / बल्क में असाइन करें |
| `cast-preset save\ | list\ | apply\ | delete` | पुस्तकों में पुन: प्रयोज्य कास्ट प्रीसेट |
| `cast-export` · `cast-import <file>` | JSON/CSV के रूप में कास्ट को राउंड-ट्रिप करें — मैन्युअल रूप से संपादित करें, या विभिन्न संस्करणों में पुन: उपयोग करें |
| `audition <char>` | एक चरित्र (`--render`) के लिए A/B रैंक वाले उम्मीदवार की आवाज़ें |
| `compile` | संवाद का पता लगाएं, वक्ताओं को निर्दिष्ट करें, भावनाओं का अनुमान लगाएं |
| `report` | गुणवत्ता संकलन: अज्ञात दर, शीर्ष बिना निर्दिष्ट पंक्तियाँ, भावनाओं का मिश्रण |
| `review-export` · `review-import <file>` | मानव-संपादित समीक्षा राउंड-ट्रिप |
| `render` | ऑडियोबुक रेंडर करें (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`) |
| `sample` · `master-check <file>` | मास्टर रिटेल नमूना · ACX ऑडियो विनिर्देश के विरुद्ध जांच करें |
| `export-chapters` · `podcast` | अध्याय क्यू शीट (ffmetadata/cue/json) · पॉडकास्ट आरएसएस फ़ीड |
| `preview` · `batch` · `diagnose` | वॉइस क्यूए क्लिप · बैच/`--manifest` · पर्यावरण जांच (जब बॉक्स रेंडर नहीं कर सकता तो गैर-शून्य मान देता है) |
| `load <file>` | एक मौजूदा `.audiobooker` प्रोजेक्ट खोलें |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | जांच करें और प्रबंधित करें |

प्रत्येक कमांड `-h/--help` का समर्थन करता है। वैश्विक ध्वज: `--silent`, `--debug`। **निकास कोड:** `0` ठीक · `1` उपयोगकर्ता त्रुटि (जिसमें एक ऐसी पुस्तक भी शामिल है जो संकलित नहीं होगी, या एक रेंडर अस्वीकार कर दिया गया क्योंकि विशेषता विफल रही) · `2` रनटाइम · `3` आंशिक (बैच)।

## कॉन्फ़िगरेशन

बार-बार ध्वज पास करने के बजाय एक बार डिफ़ॉल्ट सेट करें — `.audiobookerrc` (TOML) अपनी पुस्तक के बगल में, या `[tool.audiobooker]` में `pyproject.toml`। प्राथमिकता है **CLI ध्वज > प्रोजेक्ट कॉन्फ़िगरेशन > उपयोगकर्ता कॉन्फ़िगरेशन (`~/.audiobookerrc`) > अंतर्निहित डिफ़ॉल्ट**।

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

एक प्लगइन (`pip install audiobooker-piper`) स्वयं को पंजीकृत करता है; कोई फोर्क आवश्यक नहीं है।

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

`render(...)` और `compile(...)` एक इंजेक्टेड `engine=` (किसी भी ऑब्जेक्ट को लागू करने वाला `TTSEngine` प्रोटोकॉल) और एक प्रगति कॉलबैक स्वीकार करते हैं — ऑडियोबुकर को GUI या सेवा में एम्बेड करें।

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
| ए. सुरक्षा आधारभूत | पास |
| बी. त्रुटि प्रबंधन | पास |
| सी. ऑपरेटर दस्तावेज़ | पास |
| डी. शिपिंग स्वच्छता | पास |
| ई. पहचान | पास |

## लाइसेंस

[MIT](LICENSE)

---

<a href="https://mcp-tool-shop.github.io/">MCP टूल शॉप</a> द्वारा निर्मित
