<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.md">English</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/audiobooker/main/assets/audiobooker-logo.png" alt="Audiobooker" width="420" />
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/@mcptoolshop/audiobooker"><img src="https://img.shields.io/npm/v/@mcptoolshop/audiobooker" alt="npm version"></a>
  <a href="https://pypi.org/project/audiobooker-ai/"><img src="https://img.shields.io/pypi/v/audiobooker-ai" alt="PyPI version"></a>
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  Turn <strong>EPUB / TXT / PDF / DOCX</strong> books into professionally narrated, multi-voice audiobooks (<strong>M4B / MP3 / Opus / FLAC</strong>) — from one command.
</p>

यह [`audiobooker-ai`](https://pypi.org/project/audiobooker-ai/) (पायथन) के लिए **`npx` रैपर** है। यह पहली बार चलाने पर एक निजी पायथन वातावरण स्थापित करता है, PyPI से निर्दिष्ट संस्करण स्थापित करता है, और वास्तविक CLI चलाता है — कोई मैन्युअल `pip` नहीं, आपके सिस्टम पायथन में कोई बदलाव नहीं।

## इसे आजमाएं

```bash
npx @mcptoolshop/audiobooker --help
```

या वैश्विक रूप से स्थापित करें:

```bash
npm install -g @mcptoolshop/audiobooker
```

पहली बार चलाने पर आपके उपयोगकर्ता डेटा निर्देशिका (`~/.local/share/audiobooker`, या विंडोज पर `%LOCALAPPDATA%\audiobooker`) के अंतर्गत एक प्रबंधित वर्चुअलएनवी स्थापित किया जाता है और `audiobooker-ai` स्थापित किया जाता है। उसके बाद हर बार यह तुरंत शुरू होता है।

**PATH में पायथन 3.10+ की आवश्यकता है** (रैपर `python3` / `py` ढूंढता है)। यदि यह उपलब्ध नहीं है, तो रैपर आपको बताता है कि इसे आपके ऑपरेटिंग सिस्टम के लिए कैसे स्थापित करें।

## त्वरित शुरुआत

```bash
# One command: parse -> auto-cast voices -> compile -> render
npx @mcptoolshop/audiobooker make mybook.epub --acx

# Or the staged workflow, with control at each step
npx @mcptoolshop/audiobooker new mybook.epub
npx @mcptoolshop/audiobooker cast --interactive
npx @mcptoolshop/audiobooker compile
npx @mcptoolshop/audiobooker render --format m4b
```

## ऑडियो रेंडरिंग (वॉइस संश्लेषण)

पार्सिंग, कास्टिंग, कंपाइलिंग और समीक्षा वर्कफ़्लो सीधे काम करते हैं। **ऑडियो रेंडरिंग** के लिए टीटीएस इंजन की आवश्यकता होती है, जो अधिक निर्भरताएँ लाता है — जब आप तैयार हों तो इसे सक्षम करें:

```bash
AUDIOBOOKER_INSTALL_EXTRAS=render npx @mcptoolshop/audiobooker render
```

रेंडरिंग के लिए M4B/MP3 असेंबली के लिए PATH में **FFmpeg** की भी आवश्यकता होती है (`winget install ffmpeg` / `brew install ffmpeg` / `apt install ffmpeg`)। अपने सेटअप की जांच करने के लिए `audiobooker diagnose` चलाएं।

## यह क्या करता है

- **मल्टी-वॉइस कास्टिंग** जिसमें स्पष्टीकरण योग्य, रैंक किए गए वॉइस सुझाव शामिल हैं; `audiobooker audition <character>` आपको प्रतिबद्ध करने से पहले उम्मीदवार आवाजों का A/B परीक्षण करने देता है।
- **संवाद पहचान + वक्ता विशेषता** (वैकल्पिक BookNLP सह-संदर्भ), भावना अनुमान और पुन: प्रयोज्य उच्चारण शब्दकोश।
- **रेंडर करने से पहले समीक्षा**: एक मानव-संपादन योग्य स्क्रिप्ट निर्यात करें, विशेषताओं को ठीक करें, फिर से आयात करें — चुपचाप कुछ भी नहीं बदला जाता है।
- **ACX / Audible मास्टरींग**: `render --acx` प्लस `master-check` ज़ोर, शिखर और शोर स्तर पर PASS/FAIL रिपोर्ट करता है।
- **प्रारूप**: M4B (अध्याय मार्कर + एम्बेडेड कवर + श्रृंखला मेटाडेटा), MP3, Opus, FLAC; प्रति-अध्याय निर्यात; खुदरा नमूना क्लिप।
- **7 भाषा प्रोफाइल** (en/fr/de/es/ja/it/pt) और सेट-एंड-फॉरगेट डिफ़ॉल्ट के लिए प्रति-पुस्तक कॉन्फ़िगरेशन फ़ाइल।

## पर्यावरण चर

| चर | प्रभाव |
|---|---|
| `AUDIOBOOKER_INSTALL_EXTRAS=render` | वॉइस इंजन (रेंडरिंग के लिए) के साथ प्रबंधित venv प्रदान करें |
| `AUDIOBOOKER_FORCE_REINSTALL=1` | शुरू से प्रबंधित वातावरण का पुनर्निर्माण करें |
| `AUDIOBOOKER_BOOTSTRAP_ROOT=<dir>` | जहां प्रबंधित venv स्थित है, उसे ओवरराइड करें |

## क्या आप pip पसंद करते हैं?

```bash
pipx install audiobooker-ai            # isolated CLI install
pip install "audiobooker-ai[render]"   # with the voice engine
```

## लिंक

- **दस्तावेज़ और हैंडबुक**: <https://mcp-tool-shop-org.github.io/audiobooker/>
- **स्रोत**: <https://github.com/mcp-tool-shop-org/audiobooker>
- **PyPI**: <https://pypi.org/project/audiobooker-ai/>

## लाइसेंस

[MIT](LICENSE) © mcp-tool-shop
