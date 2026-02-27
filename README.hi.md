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
  AI Audiobook Generator — Convert EPUB/TXT books into professionally narrated audiobooks using multi-voice synthesis.
</p>

## विशेषताएं

- **बहु-आवाज संश्लेषण**: प्रत्येक पात्र के लिए अद्वितीय आवाजें असाइन करें।
- **संवाद पहचान**: स्वचालित रूप से उद्धृत संवाद और कथन की पहचान करता है।
- **भावना अनुमान**: कॉन्फ़िगर करने योग्य आत्मविश्वास के साथ नियम + शब्दावली-आधारित भावना लेबलिंग।
- **आवाज सुझाव**: वक्ता के अनुसार व्याख्या करने योग्य, रैंक किए गए आवाज सुझाव।
- **BookNLP एकीकरण**: वैकल्पिक रूप से, एनएलपी-संचालित वक्ता संदर्भ समाधान।
- **रेंडर करने से पहले समीक्षा**: विशेषताओं को ठीक करने के लिए मानव-संपादनीय समीक्षा प्रारूप।
- **स्थायी रेंडर कैश**: पूर्ण अध्यायों को फिर से संश्लेषित किए बिना, विफल रेंडर को फिर से शुरू करें।
- **गतिशील प्रगति और अनुमानित समय**: वास्तविक समय में रेंडरिंग स्थिति और अनुमानित पूर्ण होने का समय।
- **विफलता रिपोर्ट**: रेंडर त्रुटियों पर संरचित JSON निदान।
- **भाषा प्रोफाइल**: भाषा-विशिष्ट नियम अमूर्तता का विस्तार।
- **M4B आउटपुट**: अध्याय नेविगेशन के साथ पेशेवर ऑडियोबुक प्रारूप।
- **परियोजना स्थिरता**: रेंडरिंग सत्र सहेजें/फिर से शुरू करें।

## स्थापना

```bash
# Clone and install
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e .

# Required: voice-soundboard for TTS
pip install -e ../voice-soundboard

# Required: FFmpeg for audio assembly
# Windows: winget install ffmpeg
# Mac: brew install ffmpeg
# Linux: apt install ffmpeg
```

## वैकल्पिक विशेषताएं

| विशेषता | इंस्टॉल करें | कॉन्फ़िगर |
|---------|---------|--------|
| **TTS rendering** | `pip install audiobooker-ai[render]` या वॉयस-साउंडबोर्ड स्थापित करें। | `render` के लिए आवश्यक। |
| **BookNLP वक्ता समाधान** | `pip install audiobooker-ai[nlp]` | `--booknlp on\ | बंद\ | ऑटो` |
| **FFmpeg audio assembly** | सिस्टम पैकेज (winget/brew/apt) | M4B आउटपुट के लिए आवश्यक। |

## शुरुआत कैसे करें

```bash
# 1. Create project from EPUB
audiobooker new mybook.epub

# 2. Get voice suggestions
audiobooker cast-suggest

# 3. Assign voices (or auto-apply suggestions)
audiobooker cast narrator bm_george --emotion calm
audiobooker cast Alice af_bella --emotion warm
# Or: audiobooker cast-apply --auto

# 4. Compile and review
audiobooker compile
audiobooker review-export     # Creates mybook_review.txt

# 5. Edit the review file to fix attributions, then import
audiobooker review-import mybook_review.txt

# 6. Render
audiobooker render
```

## समीक्षा कार्यप्रवाह

समीक्षा कार्यप्रवाह आपको रेंडर करने से पहले संकलित स्क्रिप्ट का निरीक्षण और सुधार करने की अनुमति देता है:

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
- `=== अध्याय शीर्षक ===` - अध्याय मार्कर।
- `@वक्ता` या `@वक्ता (भावना)` - वक्ता टैग।
- `# टिप्पणी` - टिप्पणियाँ (आयात करते समय अनदेखा)।
- अवांछित वाक्यों को हटाने के लिए ब्लॉक हटाएं।
- विशेषताओं को ठीक करने के लिए `@अज्ञात` को `@वास्तविक नाम` में बदलें।

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

## सीएलआई कमांड

| कमांड | विवरण |
|---------|-------------|
| `audiobooker new <file>` | EPUB/TXT से परियोजना बनाएं। |
| `audiobooker cast <char> <voice>` | पात्र को आवाज असाइन करें। |
| `audiobooker cast-suggest` | अनिर्दिष्ट वक्ताओं के लिए आवाज सुझाव दें। |
| `audiobooker cast-apply --auto` | शीर्ष आवाज सुझावों को स्वचालित रूप से लागू करें। |
| `audiobooker compile` | अध्यायों को वाक्यों में संकलित करें। |
| `audiobooker review-export` | मानव समीक्षा के लिए स्क्रिप्ट निर्यात करें। |
| `audiobooker review-import <file>` | संपादित समीक्षा फ़ाइल आयात करें। |
| `audiobooker render` | ऑडियोबुक रेंडर करें। |
| `audiobooker info` | परियोजना जानकारी दिखाएं। |
| `audiobooker voices` | उपलब्ध आवाजों की सूची बनाएं। |
| `audiobooker chapters` | अध्यायों की सूची बनाएं। |
| `audiobooker speakers` | पहचाने गए वक्ताओं की सूची बनाएं। |
| `audiobooker from-stdin` | पाइप्ड टेक्स्ट से परियोजना बनाएं। |

## आर्किटेक्चर

```
audiobooker/
├── parser/          # EPUB, TXT parsing
├── casting/         # Dialogue detection, voice assignment, suggestions
├── language/        # Language profiles (en, extensible)
├── nlp/             # BookNLP adapter, emotion inference, speaker resolver
├── renderer/        # Audio synthesis, cache, progress, failure reports
├── review.py        # Review format export/import
└── cli.py           # Command-line interface
```

**प्रवाह:**
```
Source File -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## समस्या निवारण

**रेंडर विफलता रिपोर्ट**: किसी भी रेंडर त्रुटि पर, Audiobooker कैश निर्देशिका में `render_failure_report.json` लिखता है। इसमें शामिल हैं:
- वह अध्याय अनुक्रमणिका और शीर्षक जहां त्रुटि हुई।
- वाक्य अनुक्रमणिका, वक्ता और पाठ पूर्वावलोकन।
- वॉयस आईडी और भावना जो संश्लेषित की जा रही थी।
- पूर्ण स्टैक ट्रेस।
- कैश और मैनिफेस्ट पथ।

**सामान्य FFmpeg मुद्दे**:
- `FFmpeg नहीं मिला`: अपने पैकेज प्रबंधक (winget/brew/apt) के माध्यम से स्थापित करें।
- `अध्याय एम्बेडिंग विफल`: Audiobooker M4A में वापस आ जाता है बिना अध्याय मार्करों के।
- ऑडियो गुणवत्ता: डिफ़ॉल्ट AAC 128kbps at 24kHz है (ProjectConfig में कॉन्फ़िगर करने योग्य)।

**कैश मुद्दे**:
- `audiobooker render --clean-cache` — सभी कैश्ड ऑडियो साफ़ करें और फिर से रेंडर करें।
- `audiobooker render --no-resume` — केवल इस रन के लिए कैश को अनदेखा करें।
- `audiobooker render --from-chapter 5` — एक विशिष्ट अध्याय से शुरू करें।

## रोडमैप

- [x] v0.1.0 - कोर पाइपलाइन (पार्स, कास्ट, संकलित, रेंडर)।
- [x] v0.2.0 - रेंडर करने से पहले समीक्षा कार्यप्रवाह।
- [x] v0.3.0 - स्थायी रेंडर कैश + फिर से शुरू करें।
- [x] v0.4.0 - भाषा प्रोफाइल + इनपुट लचीलापन।
- [x] v0.5.0 - BookNLP, भावना अनुमान, वॉयस सुझाव, यूएक्स पॉलिश।

## सुरक्षा और डेटा का दायरा

- **डेटा जो एक्सेस किया जाता है:** स्थानीय फ़ाइल सिस्टम से EPUB/TXT फ़ाइलें पढ़ता है। ऑडियो फ़ाइलें और कैश मैनिफेस्ट को आउटपुट निर्देशिकाओं में लिखता है। वैकल्पिक रूप से, TTS के लिए वॉयस-साउंडबोर्ड और ऑडियो असेंबली के लिए FFmpeg का उपयोग करता है।
- **डेटा जो एक्सेस नहीं किया जाता है:** कोई नेटवर्क अनुरोध नहीं। कोई टेलीमेट्री नहीं। कोई उपयोगकर्ता डेटा भंडारण नहीं। कोई क्रेडेंशियल या टोकन नहीं।
- **आवश्यक अनुमतियाँ:** इनपुट पुस्तक फ़ाइलों तक पढ़ने की पहुंच। आउटपुट निर्देशिकाओं तक लिखने की पहुंच। वैकल्पिक: PATH पर FFmpeg।

## स्कोरकार्ड

| गेट | स्थिति |
|------|--------|
| ए. सुरक्षा आधारभूत स्तर | पास |
| बी. त्रुटि प्रबंधन | पास |
| सी. ऑपरेटर दस्तावेज़ | पास |
| डी. शिपिंग स्वच्छता | पास |
| ई. पहचान | पास |

## लाइसेंस

[MIT](LICENSE)

---

MCP टूल शॉप द्वारा निर्मित: <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a
