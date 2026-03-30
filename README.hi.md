<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.md">English</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="assets/audiobooker-logo.jpg" alt="Audiobooker" width="400" />
</p>

<h1 align="center">Audiobooker</h1>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/mcp-tool-shop-org/audiobooker"><img src="https://codecov.io/gh/mcp-tool-shop-org/audiobooker/branch/main/graph/badge.svg" alt="codecov"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  AI Audiobook Generator — Convert EPUB/TXT/PDF books into professionally narrated audiobooks using multi-voice synthesis.
</p>

## विशेषताएं

### इनपुट और पार्सिंग
- **EPUB / TXT / Markdown** स्रोतों का विश्लेषण, जिसमें अध्यायों का पता लगाना शामिल है।
- **PDF समर्थन** (वैकल्पिक): PyMuPDF के माध्यम से PDF फ़ाइलों से टेक्स्ट निकालें (`pip install -e '.[pdf]'`)
- **टेक्स्ट सामान्यीकरण**: स्मार्ट-कोट सफाई, व्हाइटस्पेस सामान्यीकरण, कॉन्फ़िगर करने योग्य टेक्स्ट क्लीनर।
- **उच्चारण ओवरराइड**: विशेष नामों और तकनीकी शब्दों के लिए कस्टम शब्द-से-उच्चारण मैपिंग।
- **फुटनोट हैंडलिंग**: कॉन्फ़िगर करने योग्य फुटनोट व्यवहार (`इनलाइन`, `एंड`, या `छोड़ें`)।

### संवाद और श्रेय
- **संवाद का पता लगाना**: स्वचालित रूप से उद्धृत संवाद और वर्णन के बीच अंतर करता है।
- **उन्नत संवाद का पता लगाना**: मल्टी-स्पीकर दृश्यों के लिए वार्तालाप टर्न-ट्रैकिंग।
- **स्टेज निर्देश**: स्क्रिप्ट में ब्रैकेट में दिए गए स्टेज निर्देशों का पता लगाना और संभालना।
- **BookNLP एकीकरण**: वैकल्पिक रूप से, NLP-संचालित स्पीकर सह-संदर्भ समाधान।
- **चरित्र उपनाम**: वैकल्पिक नामों को एक प्राथमिक चरित्र से जोड़ना।

### आवाज और कास्टिंग
- **मल्टी-वॉइस संश्लेषण**: प्रत्येक चरित्र के लिए अद्वितीय आवाजें असाइन करें।
- **आवाज सुझाव**: प्रत्येक स्पीकर के लिए व्याख्यात्मक, रैंक किए गए आवाज सुझाव।
- **भावना अनुमान**: कॉन्फ़िगर करने योग्य आत्मविश्वास के साथ नियम + शब्दावली आधारित भावना लेबलिंग।
- **प्रति-चरित्र आवाज पैरामीटर**: गति (0.5--2.0) और प्रत्येक स्पीकर के लिए भावना।
- **SSML प्रीप्रोसेसिंग**: स्पीच सिंथेसिस मार्कअप लैंग्वेज समर्थन, जो बेहतर नियंत्रण प्रदान करता है।

### रेंडरिंग और आउटपुट
- **समानांतर रेंडरिंग**: `--jobs N` के साथ मल्टी-वर्कर अध्याय रेंडरिंग।
- **एकाधिक आउटपुट प्रारूप**: MP3, M4B, WAV, OGG, FLAC।
- **ऑडियो सामान्यीकरण**: अध्यायों में सुसंगत वॉल्यूम स्तर।
- **कवर आर्ट एम्बेडिंग**: EPUB से निकाला गया या उपयोगकर्ता द्वारा प्रदान किया गया, M4B आउटपुट में एम्बेडेड।
- **स्थायी रेंडर कैश**: पूर्ण अध्यायों को फिर से संश्लेषित किए बिना विफल रेंडर को फिर से शुरू करें।
- **डायनामिक प्रगति और ETA**: अनुमानित पूर्णता समय के साथ रीयल-टाइम रेंडरिंग स्थिति।
- **विफलता रिपोर्ट**: रेंडर त्रुटियों पर संरचित JSON निदान।

### भाषा और स्थानीयकरण
- **5 भाषा प्रोफाइल**: अंग्रेजी, फ्रेंच, जर्मन, स्पेनिश, जापानी (`--lang en|fr|de|es|ja`)।
- **विस्तार योग्य प्रोफाइल सिस्टम**: `LanguageProfile` सार का उपयोग करके नई भाषाएं जोड़ें।

### कार्यप्रवाह और उत्पादकता
- **रेंडर करने से पहले समीक्षा**: श्रेय को ठीक करने के लिए मानव-संपादनीय समीक्षा प्रारूप।
- **परियोजना अंतर**: अध्याय और वाक्य परिवर्तनों को देखने के लिए दो परियोजना संस्करणों की तुलना करें।
- **बैच प्रोसेसिंग**: `audiobooker batch` के साथ एक ही बार में कई पुस्तकों को संसाधित करें।
- **ड्राई-रन मोड**: निष्पादित किए बिना रेंडर या बैच संचालन का पूर्वावलोकन करें (`--dry-run`)।
- **आवाज परीक्षण**: आवाज असाइनमेंट को मान्य करने के लिए एक छोटा नमूना रेंडर करें (`audiobooker preview`)।
- **अध्याय प्रबंधन**: रेंडर करने से पहले अध्यायों को मर्ज, विभाजित और बाहर करें।
- **भावना प्रबंधन**: संकलन के बाद प्रति-वाक्य भावनाओं की सूची बनाएं और ओवरराइड करें।
- **डेस्कटॉप सूचनाएं**: जब लंबे समय तक चलने वाले रेंडर पूरा हो जाते हैं तो सूचनाएं प्राप्त करें।
- **परियोजना निरंतरता**: रेंडरिंग सत्र सहेजें/फिर से शुरू करें।

## स्थापना

```bash
# Clone and install
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e .

# Required: voice-soundboard for TTS
git clone https://github.com/mcp-tool-shop-org/voice-soundboard.git ../voice-soundboard
pip install -e ../voice-soundboard

# Required: FFmpeg for audio assembly
# Windows: winget install ffmpeg
# Mac: brew install ffmpeg
# Linux: apt install ffmpeg
```

## वैकल्पिक विशेषताएं

| विशेषता | स्थापित करें | कॉन्फ़िग |
|---------|---------|--------|
| **TTS rendering** | `pip install -e '.[render]'` या वॉयस-साउंडबोर्ड स्थापित करें। | `render` के लिए आवश्यक |
| **BookNLP स्पीकर रिज़ॉल्यूशन** | `pip install -e '.[nlp]'` | `--booknlp on\ | off\ | auto` |
| **PDF input** | `pip install -e '.[pdf]'` | `audiobooker new book.pdf` |
| **Rich progress bars** | `pip install -e '.[rich]'` | रनटाइम पर स्वचालित रूप से पता लगाया गया। |
| **FFmpeg audio assembly** | सिस्टम पैकेज (winget/brew/apt) | M4B आउटपुट के लिए आवश्यक। |

## त्वरित शुरुआत

```bash
# 1. Create a project from your book
audiobooker new mybook.epub

# 2. Cast voices to characters
audiobooker cast narrator bm_george --emotion calm
audiobooker cast Alice af_bella --emotion warm
# Or auto-cast: audiobooker cast-suggest && audiobooker cast-apply --auto

# 3. Compile (dialogue detection + speaker attribution)
audiobooker compile

# 4. Review and correct the script (optional but recommended)
audiobooker review-export        # Creates mybook_review.txt
# Edit the file to fix attributions, then:
audiobooker review-import mybook_review.txt

# 5. Render the audiobook
audiobooker render
```

## समीक्षा कार्यप्रवाह

समीक्षा कार्यप्रवाह आपको रेंडर करने से पहले संकलित स्क्रिप्ट का निरीक्षण करने और उसे ठीक करने की अनुमति देता है:

```bash
# Export to review format
audiobooker review-export

# Edit the file (example: mybook_review.txt)
# === Chapter 1 ===
#
# @narrator
# The door creaked open.
#
# @Unknown              <-- Change this to @Marcus
# "Hello?" he whispered.
#
# @Sarah (worried)      <-- Emotions are preserved
# "Is anyone there?"

# Import corrections
audiobooker review-import mybook_review.txt

# Render with corrected attributions
audiobooker render
```

**समीक्षा फ़ाइल प्रारूप:**
- `=== अध्याय शीर्षक ===` - अध्याय मार्कर
- `@Speaker` या `@Speaker (भावना)` - वक्ता टैग
- `# टिप्पणी` - टिप्पणियाँ (आयात करते समय अनदेखा की जाती हैं)
- अवांछित वाक्यों को हटाने के लिए ब्लॉक हटाएं।
- `@Unknown` को `@ActualName` में बदलें ताकि वक्ता का सही नाम दर्शाया जा सके।

## पायथन एपीआई

```python
from audiobooker import AudiobookProject

# Create from EPUB
project = AudiobookProject.from_epub("mybook.epub")

# Or from raw text
project = AudiobookProject.from_string("Chapter 1\n\nHello world.", title="My Book")

# Cast voices
project.cast("narrator", "bm_george", emotion="calm")
project.cast("Alice", "af_bella", emotion="warm")

# Compile (detect dialogue, attribute speakers, infer emotions)
project.compile()

# Review workflow
review_path = project.export_for_review()
# ... edit the file ...
project.import_reviewed(review_path)

# Render to M4B (with automatic resume on re-run)
project.render("mybook.m4b")

# Save project for later
project.save("mybook.audiobooker")
```

## कमांड लाइन इंटरफेस (CLI) कमांड

| कमांड | विवरण |
|---------|-------------|
| `audiobooker new <file>` | EPUB/TXT/MD/PDF से प्रोजेक्ट बनाएं |
| `audiobooker load <project>` | मौजूदा `.audiobooker` प्रोजेक्ट लोड करें |
| `audiobooker from-stdin` | पाइप्ड टेक्स्ट से प्रोजेक्ट बनाएं |
| `audiobooker cast <char> <voice>` | चरित्र को आवाज असाइन करें |
| `audiobooker cast-suggest` | अनिर्दिष्ट वक्ताओं के लिए आवाजों का सुझाव दें |
| `audiobooker cast-apply --auto` | शीर्ष आवाज सुझावों को स्वचालित रूप से लागू करें |
| `audiobooker compile` | अध्यायों को वाक्यों में बदलें |
| `audiobooker review-export` | मानव समीक्षा के लिए स्क्रिप्ट निर्यात करें |
| `audiobooker review-import <file>` | संपादित समीक्षा फ़ाइल आयात करें |
| `audiobooker render` | ऑडियोबुक बनाएं ( `--dry-run`, `--jobs N`, `--format`, `--cover` का समर्थन करता है) |
| `audiobooker preview` | आवाज की पुष्टि के लिए एक छोटा नमूना बनाएं (`--chapter N`, `--seconds S`) |
| `audiobooker batch <files...>` | एक साथ कई पुस्तकों को संसाधित करें (`--dry-run` का समर्थन करता है) |
| `audiobooker info` | प्रोजेक्ट की जानकारी दिखाएं |
| `audiobooker status` | रेंडर/कैश स्थिति दिखाएं |
| `audiobooker voices` | उपलब्ध आवाजों की सूची बनाएं (`--gender`, `--search` का समर्थन करता है) |
| `audiobooker chapters` | अध्याय के शीर्षकों और अनुक्रम संख्याओं की सूची बनाएं |
| `audiobooker speakers` | पहचाने गए वक्ताओं की सूची बनाएं |
| `audiobooker cache info` | `clean` | `clean-failed` | रेंडर कैश का प्रबंधन करें |
| `audiobooker diagnose` | पर्यावरण की जांच करें (निर्भरताएँ, आवाज इंजन, FFmpeg) |

## कमांड लाइन इंटरफेस (CLI) का संपूर्ण संदर्भ

प्रत्येक कमांड विस्तृत उपयोग के लिए `-h` / `--help` का समर्थन करता है। मुख्य विकल्प:

- **`new`**: `-o <project>`, `--lang <code>` (en/fr/de/es/ja)
- **`cast`**: `--emotion <emotion>`, `--speed <0.5-2.0>`
- **`compile`**: `--booknlp on|off|auto`
- **`render`**: `--dry-run`, `--no-resume`, `--from-chapter N`, `--allow-partial`, `--clean-cache`, `--jobs N`, `-o <path>`, `--format mp3|m4b|wav|ogg|flac`, `--cover <image>`
- **`preview`**: `--chapter N`, `--seconds S`, `-o <path>`
- **`batch`**: `--dry-run`, `--jobs N`, `--format <fmt>`, `--lang <code>`, `--output-dir <dir>`
- **`voices`**: `--gender <male|female>`, `--search <query>`
- **`info`**: `--verbose`

## आर्किटेक्चर

```
audiobooker/
├── parser/          # EPUB, TXT, PDF parsing
├── casting/         # Dialogue detection, voice assignment, suggestions
├── language/        # Language profiles (en, extensible)
├── nlp/             # BookNLP adapter, emotion inference, speaker resolver
├── renderer/        # Audio synthesis, cache, progress, failure reports
├── review.py        # Review format export/import
└── cli.py           # Command-line interface
```

**प्रक्रिया:**
```
Source File (EPUB/TXT/PDF) -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## सामान्य समस्याएं

| समस्या | समाधान |
|---------|-----|
| **FFmpeg not found** | अपने पैकेज मैनेजर के माध्यम से स्थापित करें: `winget install ffmpeg` (Windows), `brew install ffmpeg` (macOS), `apt install ffmpeg` (Linux)। FFmpeg को PATH में होना चाहिए। |
| **"voice-soundboard" स्थापित नहीं है** | समानांतर रिपॉजिटरी को क्लोन और स्थापित करें: `git clone https://github.com/mcp-tool-shop-org/voice-soundboard.git ../voice-soundboard && pip install -e ../voice-soundboard`. या `pip install -e '.[render]'` के साथ स्थापित करें। |
| **BookNLP त्रुटियाँ या धीमी शुरुआत** | BookNLP वैकल्पिक है। यदि आपको NLP वक्ता पहचान की आवश्यकता नहीं है, तो `--booknlp off` सेट करें या इसे `auto` पर छोड़ दें (सुरक्षित विकल्प)। केवल तभी `pip install -e '.[nlp]'` के साथ स्थापित करें जब आवश्यक हो। |

पूर्ण समस्या निवारण मार्गदर्शन के लिए [निर्देशिका](docs/handbook.md#15-troubleshooting) देखें।

## समस्या निवारण

**रेंडर विफलता रिपोर्ट**: किसी भी रेंडर त्रुटि पर, Audiobooker `render_failure_report.json` को कैश निर्देशिका में लिखता है। इसमें शामिल हैं:
- वह अध्याय अनुक्रमणिका और शीर्षक जहाँ त्रुटि हुई
- वाक्य अनुक्रमणिका, वक्ता और पाठ का पूर्वावलोकन
- आवाज आईडी और भावना जो संश्लेषित की जा रही थी
- पूर्ण स्टैक ट्रेस
- कैश और मैनिफेस्ट पथ

**सामान्य FFmpeg समस्याएं**:
- `FFmpeg नहीं मिला`: अपने पैकेज मैनेजर (winget/brew/apt) के माध्यम से स्थापित करें
- `अध्याय एम्बेडिंग विफल`: Audiobooker M4A में वापस आ जाता है बिना अध्याय मार्करों के
- ऑडियो गुणवत्ता: डिफ़ॉल्ट AAC 128kbps at 24kHz है (ProjectConfig में कॉन्फ़िगर करने योग्य)

**कैश संबंधी समस्याएं:**
- `audiobooker render --clean-cache` — सभी कैश्ड ऑडियो को साफ़ करें और फिर से रेंडर करें।
- `audiobooker render --no-resume` — इस बार केवल कैशे को अनदेखा करें।
- `audiobooker render --from-chapter 5` — किसी विशिष्ट अध्याय से शुरू करें।

## रोडमैप

- [x] मुख्य प्रक्रिया (पार्स, कास्ट, कंपाइल, रेंडर)
- [x] रेंडर करने से पहले समीक्षा प्रक्रिया
- [x] स्थायी रेंडर कैश + पुनः आरंभ करने की सुविधा
- [x] भाषा प्रोफाइल + इनपुट में लचीलापन
- [x] बुकएनएलपी, भावना अनुमान, आवाज सुझाव, यूएक्स में सुधार
- [x] v1.0.0 - उत्पादन संस्करण

## सुरक्षा और डेटा का दायरा

- **डेटा जो एक्सेस किया जाता है:** स्थानीय फ़ाइल सिस्टम से ईपीयूबी/टीएक्सटी फ़ाइलें पढ़ता है। ऑडियो फ़ाइलें और कैश मैनिफेस्ट आउटपुट निर्देशिकाओं में लिखता है। वैकल्पिक रूप से, टीटीएस के लिए वॉयस-साउंडबोर्ड और ऑडियो संयोजन के लिए एफएफमेग का उपयोग करता है।
- **डेटा जो एक्सेस नहीं किया जाता है:** कोई नेटवर्क अनुरोध नहीं। कोई टेलीमेट्री नहीं। कोई उपयोगकर्ता डेटा भंडारण नहीं। कोई क्रेडेंशियल या टोकन नहीं।
- **आवश्यक अनुमतियाँ:** इनपुट पुस्तक फ़ाइलों तक पढ़ने की पहुंच। आउटपुट निर्देशिकाओं तक लिखने की पहुंच। वैकल्पिक: एफएफमेग PATH पर होना चाहिए।

## स्कोरकार्ड

| गेट | स्थिति |
|------|--------|
| A. सुरक्षा आधारभूत | पास |
| B. त्रुटि प्रबंधन | पास |
| C. ऑपरेटर दस्तावेज़ | पास |
| D. शिपिंग स्वच्छता | पास |
| E. पहचान | पास |

## लाइसेंस

[एमआईटी](LICENSE)

---

<a href="https://mcp-tool-shop.github.io/">एमसीपी टूल शॉप</a> द्वारा निर्मित।
