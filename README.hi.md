<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="assets/audiobooker-logo.jpg" alt="Audiobooker" width="400" />
</p>

<h1 align="center">Audiobooker</h1>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  AI Audiobook Generator — Convert EPUB/TXT books into professionally narrated audiobooks using multi-voice synthesis.
</p>

## विशेषताएं।

- **बहु-आवाज़ संश्लेषण:** प्रत्येक पात्र के लिए अलग-अलग आवाज़ें निर्धारित करें।
- **संवाद पहचान:** स्वचालित रूप से उद्धृत संवाद और वर्णन के बीच अंतर करें।
- **भावना अनुमान:** कॉन्फ़िगर करने योग्य आत्मविश्वास स्तर के साथ, नियमों और शब्दावली का उपयोग करके भावनाओं को वर्गीकृत करें।
- **आवाज़ सुझाव:** प्रत्येक वक्ता के लिए स्पष्ट, क्रमबद्ध आवाज़ों के सुझाव।
- **BookNLP एकीकरण:** वैकल्पिक रूप से, एनएलपी-आधारित वक्ता संदर्भ समाधान।
- **रेंडर करने से पहले समीक्षा:** मानव-संपादनीय समीक्षा प्रारूप, जिसका उपयोग गलत विवरणों को ठीक करने के लिए किया जा सकता है।
- **स्थायी रेंडर कैश:** अधूरे रेंडर को फिर से शुरू करें, बिना पहले से पूरे किए गए अध्यायों को फिर से संश्लेषित किए।
- **गतिशील प्रगति और अनुमानित समय:** वास्तविक समय में रेंडरिंग की स्थिति और अनुमानित पूर्ण होने का समय प्रदर्शित करें।
- **त्रुटि रिपोर्ट:** रेंडरिंग त्रुटियों के लिए संरचित JSON निदान।
- **भाषा प्रोफाइल:** भाषा-विशिष्ट नियमों का विस्तार योग्य सार।
- **M4B आउटपुट:** पेशेवर ऑडियोबुक प्रारूप, जिसमें अध्याय नेविगेशन शामिल है।
- **परियोजना का संरक्षण:** रेंडरिंग सत्रों को सहेजें/फिर से शुरू करें।

## स्थापना।

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

## वैकल्पिक विशेषताएं।

| विशेषता। | स्थापित करें। | कॉन्फ़िगरेशन। |
| ज़रूर, मैं आपकी मदद कर सकता हूँ। कृपया वह अंग्रेजी पाठ प्रदान करें जिसका आप हिंदी में अनुवाद करवाना चाहते हैं। | ज़रूर, मैं आपकी मदद कर सकता हूँ। कृपया वह अंग्रेजी पाठ प्रदान करें जिसका आप हिंदी में अनुवाद करवाना चाहते हैं। | ज़रूर, मैं आपकी मदद कर सकता हूँ। कृपया वह अंग्रेजी पाठ प्रदान करें जिसका आप हिंदी में अनुवाद करवाना चाहते हैं। |
| **TTS rendering** | `pip install audiobooker-ai[render]` या वॉइस-साउंडबोर्ड स्थापित करें। | यह `render` फ़ंक्शन के लिए आवश्यक है। |
| **बुकएनएलपी: वक्ता की पहचान** | `pip install audiobooker-ai[nlp]` | "--booknlp on" का हिंदी में अनुवाद:

"--बुकएनएलपी चालू करें" या "--बुकएनएलपी को सक्रिय करें"। |off\|auto` |
| **FFmpeg audio assembly** | सिस्टम पैकेज (विंगेट/ब्रू/एप्ट) | एम4बी (M4B) फ़ाइल बनाने के लिए आवश्यक। |

## शुरुआत कैसे करें।

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

## समीक्षा प्रक्रिया का विवरण।

समीक्षा प्रक्रिया आपको संकलित स्क्रिप्ट को देखने और उसमें सुधार करने की अनुमति देती है, इससे पहले कि उसे प्रदर्शित किया जाए।

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

**समीक्षा फ़ाइल का प्रारूप:**
- `=== अध्याय का शीर्षक ===` - अध्याय के विभाजक
- `@वक्ता` या `@वक्ता (भावना)` - वक्ता के नाम
- `# टिप्पणी` - टिप्पणियाँ (आयात करते समय इन्हें अनदेखा किया जाता है)
- अवांछित वाक्यों को हटाने के लिए ब्लॉक हटाएं।
- `@अज्ञात` को `@वास्तविक नाम` में बदलें ताकि सही ढंग से श्रेय दिया जा सके।

## पायथन एपीआई (Python API)

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

## कमांड लाइन इंटरफेस (सीएलआई) के आदेश।

| आदेश। | विवरण। |
| ज़रूर, मैं आपकी मदद कर सकता हूँ। कृपया वह अंग्रेजी पाठ प्रदान करें जिसका आप हिंदी में अनुवाद करवाना चाहते हैं। | कृपया वह अंग्रेजी पाठ प्रदान करें जिसका आप हिंदी में अनुवाद करवाना चाहते हैं। मैं उसका सटीक और उचित अनुवाद करने के लिए तैयार हूं। |
| `audiobooker new <file>` | ईपीयूबी/टीएक्सटी फ़ाइल से प्रोजेक्ट बनाएं। |
| `audiobooker cast <char> <voice>` | पात्र को आवाज़ दें। |
| `audiobooker cast-suggest` | उन वक्ताओं के लिए संभावित आवाज़ों का सुझाव दें जिन्हें अभी तक चुना नहीं गया है। |
| `audiobooker cast-apply --auto` | स्वचालित रूप से शीर्ष सुझावों को लागू करें। |
| `audiobooker compile` | अध्याय को वाक्यों में परिवर्तित करें। |
| `audiobooker review-export` | मानव समीक्षा के लिए निर्यात स्क्रिप्ट। |
| `audiobooker review-import <file>` | संपादित समीक्षा फ़ाइल आयात करें। |
| `audiobooker render` | ऑडियोबुक को प्रस्तुत करें। |
| `audiobooker info` | परियोजना की जानकारी प्रदर्शित करें। |
| `audiobooker voices` | उपलब्ध आवाज़ों की सूची दिखाएं। |
| `audiobooker chapters` | अध्यायों की सूची बनाएं। |
| `audiobooker speakers` | पहचाने गए वक्ताओं की सूची प्रदर्शित करें। |
| `audiobooker from-stdin` | पाइप्ड टेक्स्ट से प्रोजेक्ट बनाएं। |

## आर्किटेक्चर।

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

## समस्या निवारण।

**रेंडरिंग त्रुटि रिपोर्ट:** किसी भी रेंडरिंग त्रुटि की स्थिति में, ऑडियोबुकर एप्लिकेशन `render_failure_report.json` नामक एक फ़ाइल को कैश डायरेक्टरी में लिखता है। इस फ़ाइल में निम्नलिखित जानकारी होती है:

- वह अध्याय संख्या और शीर्षक जहां त्रुटि हुई।
- वाक्य संख्या, वक्ता और पाठ का पूर्वावलोकन।
- वह वॉयस आईडी और भावना जो संश्लेषित की जा रही थी।
- पूर्ण स्टैक ट्रेस (त्रुटि का विस्तृत विवरण)।
- कैश और मैनिफेस्ट फ़ाइलों के पथ।

**सामान्य एफएफmpeg समस्याएं:**
- `एफएफmpeg नहीं मिला`: इसे अपने पैकेज मैनेजर (विंगेट/ब्रू/एप्ट) के माध्यम से स्थापित करें।
- `अध्याय एम्बेडिंग विफल`: ऑडियोबुकर, अध्याय मार्करों के बिना, M4A फॉर्मेट का उपयोग करता है।
- ऑडियो गुणवत्ता: डिफ़ॉल्ट रूप से AAC 128kbps की दर पर 24kHz पर सेट है (जिसे प्रोजेक्टकॉन्फिग में बदला जा सकता है)।

**कैश संबंधी समस्याएं:**
- `audiobooker render --clean-cache` — सभी कैश्ड ऑडियो को हटाएं और फिर से रेंडर करें।
- `audiobooker render --no-resume` — इस बार केवल चलाने के लिए कैश को अनदेखा करें।
- `audiobooker render --from-chapter 5` — किसी विशेष अध्याय से शुरू करें।

## रणनीति।

- [x] v0.1.0 - मुख्य प्रक्रिया (पार्सिंग, रूपांतरण, संकलन, रेंडरिंग)
- [x] v0.2.0 - रेंडरिंग से पहले समीक्षा प्रक्रिया
- [x] v0.3.0 - स्थायी रेंडर कैश + पुनः आरंभ करने की सुविधा
- [x] v0.4.0 - भाषा प्रोफाइल + इनपुट में लचीलापन
- [x] v0.5.0 - बुकएनएलपी, भावना अनुमान, आवाज सुझाव, यूएक्स में सुधार

## लाइसेंस

एमआईटी
