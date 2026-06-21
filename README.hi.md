<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.md">English</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="assets/audiobooker-logo.png" alt="Audiobooker" width="500" />
</p>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/audiobooker-ai/"><img src="https://img.shields.io/pypi/v/audiobooker-ai" alt="PyPI"></a>
  <a href="https://www.npmjs.com/package/@mcptoolshop/audiobooker"><img src="https://img.shields.io/npm/v/@mcptoolshop/audiobooker" alt="npm"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  Turn <strong>EPUB / TXT / PDF / DOCX</strong> books into professionally narrated, multi-voice audiobooks — <strong>M4B / MP3 / Opus / FLAC</strong>, with chapter markers, cover art, and <strong>ACX/Audible-ready</strong> mastering. From one command.
</p>

```bash
npx @mcptoolshop/audiobooker make mybook.epub --acx
```

ऑडियोबुकर संवाद का पता लगाता है, प्रत्येक पात्र के लिए एक विशिष्ट आवाज निर्धारित करता है, भावनाओं को समझता है, आपको किसी भी सेकंड को प्रस्तुत करने से पहले सब कुछ समीक्षा और सही करने देता है, फिर परिणाम को मानकों के अनुसार अनुकूलित करता है - इसलिए आउटपुट एक *सबमिट करने योग्य* ऑडियोबुक होता है, न कि केवल उत्पन्न ऑडियो।

## इंस्टॉल करें

**शून्य-स्थापना (नोड):**
```bash
npx @mcptoolshop/audiobooker --help
```

**पायथन (सीएलआई):**
```bash
pipx install audiobooker-ai            # isolated CLI
uvx audiobooker --help                 # zero-install trial
pip install "audiobooker-ai[render]"   # with the TTS voice engine
```

**ऑडियो प्रस्तुत करने** के लिए [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) टीटीएस इंजन ( `[render]` एक्स्ट्रा) और **एफएफmpeg** को PATH में स्थापित करना होगा (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`)। प्रस्तुत करने से पहले के सभी चरण - पार्स, कास्ट, कंपाइल, समीक्षा - इसके बिना भी काम करते हैं। अपनी सेटअप की जांच करने के लिए `audiobooker diagnose` चलाएं।

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
- **ईपीयूबी, टीएक्सटी, मार्कडाउन, पीडीएफ, डीओसीएक्स**, या **प्रत्येक अध्याय की फाइलों का एक फ़ोल्डर** (स्क्रिवनर/ऑब्सिडियन/क्रमिक उपन्यास)।
- **टीओसी-संचालित ईपीयूबी विभाजन** - पुस्तक की अपनी सामग्री तालिका से अध्याय सीमाएं और शीर्षक।
- **डीओसीएस** वर्ड `हेडिंग 1/2`/`टाइटल` शैलियों पर विभाजित होता है; **पीडीएफ** शीर्षकों का पता लगाता है (स्कैन किए गए पीडीएफ के लिए सुरक्षा के साथ); कस्टम `--चैप्टर-डेलिमिटर`।
- स्मार्ट टेक्स्ट क्लीनिंग, मार्कडाउन-जागरूक स्ट्रिपिंग, पाद लेखों को संभालना और एक **पुन: प्रयोज्य उच्चारण शब्दकोश** (`pronunciation import/export`, सीएसवी/जेएसओएन, जिसमें फोनम पासथ्रू हो)।

### कास्टिंग और विशेषता
- **बहु-आवाज संश्लेषण** स्पष्टीकरण योग्य, रैंक की गई आवाज **सुझावों** और प्रति पात्र उम्मीदवारों के लिए एक **`ऑडिशन`** कमांड के साथ।
- **इंटरैक्टिव कास्टिंग**, लिंग/भूमिका द्वारा **बल्क `कास्ट-फिल`**, श्रृंखला में पुन: प्रयोज्य **नाममात्र कास्ट प्रीसेट**, और सहयोगियों के लिए **सीएसवी कास्ट शीट**।
- **संवाद का पता लगाना + वक्ता विशेषता** (वैकल्पिक **बुकएनएलपी** सह-संदर्भ), **उपनाम ऑटो-डिस्कवरी**, और समायोज्य **तीव्रता**, **दृश्य-स्तरीय मनोदशा** और शैली **प्रीसेट पैक** के साथ **भावना अनुमान**।

### प्रस्तुत करना और आउटपुट
- **एम4बी** (अध्याय मार्कर + एम्बेडेड कवर + श्रृंखला मेटाडेटा), **एमपी3**, **ओपस**, **एफएलएसी**; प्रति अध्याय निर्यात; **पॉडकास्ट/आरएसएस** फ़ीड निर्यात।
- **एसीएक्स/ऑडिबल मास्टरींग** (`--acx`) + एक **`मास्टर-चेक`** जो जोर, शिखर और शोर स्तर पर पास/फेल की रिपोर्ट करता है; खुदरा **`सैंपल`** क्लिप।
- समानांतर प्रस्तुत करना, एक **स्थायी रेंडर कैश** जिसमें फिर से शुरू करने की सुविधा हो, गतिशील प्रगति + ईटीए, और संरचित विफलता रिपोर्ट।

### कार्यप्रवाह और पारिस्थितिकी तंत्र
- **`मेक`** वन-शॉट पाइपलाइन · **कॉन्फ़िगरेशन फ़ाइल** (`.audiobookerrc` / `[tool.audiobooker]`) · **`--वॉच`** मोड · **मैनिफेस्ट-संचालित बैच** · शेल पूर्णता।
- **7 भाषा प्रोफाइल** (en/fr/de/es/ja/it/pt) · **प्लग करने योग्य टीटीएस इंजन** (`--इंजन`, एंट्री-पॉइंट - पाइपर/कोकी/एलेवनलैब्स लाएं) · अधिकांश कमांड पर स्क्रिप्टेबल `--json` · संरचित निकास कोड।

## एसीएक्स / ऑडिबल में प्रकाशित करना

ऑडियोबुकर सीधे मापने योग्य एसीएक्स सबमिशन विशिष्टताओं को लक्षित करता है:

```bash
audiobooker render --acx               # loudnorm -20 LUFS, -3 dBTP peak, 44.1k, 192k
audiobooker master-check book.m4b      # PASS/FAIL: RMS [-23,-18], peak <= -3 dB, floor <= -60 dB
audiobooker sample --duration 180      # a mastered retail sample clip
```

`मास्टर-चेक` मापने योग्य आवश्यकताओं (जोर, शिखर, शोर स्तर) की पुष्टि करता है। एसीएक्स में व्यक्तिपरक/क्यूसी मानदंड भी हैं जिनकी एक उपकरण प्रमाणिकता नहीं कर सकता - लेकिन आप जोर उल्लंघन के लिए फिर कभी अस्वीकृत नहीं होंगे।

## सीएलआई कमांड

| कमांड | विवरण |
|---------|-------------|
| `make <file>` | वन-शॉट: नया → कंपाइल → ऑटो-कास्ट → रेंडर |
| `new <file\ | folder>` | ईपीयूबी/टीएक्सटी/एमडी/पीडीएफ/डीओसीएस या एक फ़ोल्डर से एक प्रोजेक्ट बनाएं |
| `from-stdin` | पाइप्ड टेक्स्ट से एक प्रोजेक्ट बनाएं |
| `cast <char> <voice>` · `cast --interactive` | आवाजें असाइन करें (या निर्देशित प्रति-वक्ता कास्टिंग) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | आवाजें सुझाएं / स्वचालित रूप से लागू करें / बल्क में असाइन करें |
| `cast-preset save\ | list\ | apply\ | delete` | पुस्तकों में पुन: प्रयोज्य कास्ट प्रीसेट |
| `audition <char>` | एक पात्र के लिए ए/बी रैंक की गई उम्मीदवार आवाजें (`--रेंडर`) |
| `compile` | संवाद का पता लगाएं, वक्ताओं को विशेषता दें, भावनाओं का अनुमान लगाएं |
| `report` | संकलन गुणवत्ता: अज्ञात दर, शीर्ष गैर-विशेषीकृत पंक्तियाँ, भावना मिश्रण |
| `review-export` · `review-import <file>` | मानव-संपादित समीक्षा राउंड-ट्रिप |
| `render` | ऑडियोबुक प्रस्तुत करें (`--acx`, `--फॉर्मेट`, `--स्प्लिट`, `--बिटरेट`, `--इंजन`, `--वॉच`, `--कवर`, `-j N`) |
| `sample` · `master-check <file>` | मास्टर्ड खुदरा नमूना · एसीएक्स अनुपालन जांच |
| `export-chapters` · `podcast` | अध्याय क्यू शीट (ffmetadata/cue/json) · पॉडकास्ट आरएसएस फ़ीड |
| `preview` · `batch` · `diagnose` | आवाज क्यूए क्लिप · बैच / `--मैनिफेस्ट` · पर्यावरण जांच |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | निरीक्षण और प्रबंधित करें |

प्रत्येक कमांड `-h/--help` का समर्थन करता है। वैश्विक ध्वज: `--साइलेंट`, `--डीबग`। **निकास कोड:** `0` ठीक · `1` उपयोगकर्ता त्रुटि · `2` रनटाइम · `3` आंशिक (बैच)।

## कॉन्फ़िगरेशन

एक बार डिफ़ॉल्ट सेट करें, ध्वजों को फिर से पास करने के बजाय - `.audiobookerrc` (TOML) आपकी पुस्तक के बगल में, या `[tool.audiobooker]` में `pyproject.toml`। प्राथमिकता है **सीएलआई ध्वज > प्रोजेक्ट कॉन्फ़िगरेशन > उपयोगकर्ता कॉन्फ़िगरेशन (`~/.audiobookerrc`) > अंतर्निहित डिफ़ॉल्ट**।

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## प्लग करने योग्य टीटीएस इंजन

डिफ़ॉल्ट इंजन `voice-soundboard` है, लेकिन संश्लेषण बैकएंड सेटटूल एंट्री-पॉइंट्स (`audiobooker.tts_engines`) के माध्यम से बदला जा सकता है:

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

`render(...)` और `compile(...)` एक इंजेक्ट किए गए `इंजन=` (किसी भी ऑब्जेक्ट जो `TTSEngine` प्रोटोकॉल को लागू करता है) और एक प्रगति कॉलबैक स्वीकार करते हैं - ऑडियोबुकर को जीयूआई या सेवा में एम्बेड करें।

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
Casting -> Review/Edit -> TTS (pluggable) -> cached audio -> FFmpeg master -> M4B/MP3/Opus/FLAC
```

## सुरक्षा और डेटा का दायरा

- **नेटवर्क:** कोई नहीं — कोई टेलीमेट्री नहीं, कोई डेटा संग्रहण नहीं, कोई क्रेडेंशियल नहीं। यह आपकी पुस्तक फ़ाइलों को पढ़ता है, ऑडियो + कैश को आपके आउटपुट निर्देशिकाओं में लिखता है।
- **अनुमतियाँ:** इनपुट तक पढ़ने की अनुमति, आउटपुट तक लिखने की अनुमति; वैकल्पिक रूप से FFmpeg + PATH पर एक TTS इंजन।
- [SECURITY.md](SECURITY.md) देखें।

## स्कोरकार्ड

| गेट | स्थिति |
|------|--------|
| ए. सुरक्षा आधारभूत संरचना | पास |
| बी. त्रुटि प्रबंधन | पास |
| सी. ऑपरेटर दस्तावेज़ | पास |
| डी. शिपिंग स्वच्छता | पास |
| ई. पहचान | पास |

## लाइसेंस

[MIT](LICENSE)

---

<a href="https://mcp-tool-shop.github.io/">MCP टूल शॉप</a> द्वारा निर्मित
