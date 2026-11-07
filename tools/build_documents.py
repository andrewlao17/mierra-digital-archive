#!/usr/bin/env python3
"""Build documents-data.js from the TEI-XML files in tei/.

Usage (run from the repository root):

    python3 tools/build_documents.py
    python3 tools/build_documents.py --tei-dir tei --out documents-data.js

Every tei/*.xml file is read (files whose names start with "_" are skipped, so
tei/_template.xml is never published). For each file the script collects:

  * descriptive metadata from the TEI header (nation, place, repository,
    date, languages, document type, licence, source link);
  * manuscript-layout facts (pages, lines, columns, support, hands);
  * counts of editorial features (additions, deletions, damage, abbreviations,
    marginal notes, named entities, ...);
  * word counts per language and each language's most frequent words.

The result is written as documents-data.js, which documents.html and
analysis.html load. Only the Python standard library is needed.

Counting rules (also shown on the analysis page):
  * Words are counted from the normalised reading: expansions, corrections and
    regularisations are counted; abbreviations, original misspellings, deleted
    text, notes and running heads are not.
  * Chinese and Japanese text has no spaces, so each Han or kana character
    counts as one word.
  * Each word is credited to the nearest xml:lang in force, so multilingual
    documents are split by language.
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET

TEI = "http://www.tei-c.org/ns/1.0"
NS = {"t": TEI}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

# Han and kana count one character per word; everything else is a run of letters
# (apostrophes and hyphens inside a word are kept).
TOKEN = re.compile(
    r"[぀-ヿ㐀-䶿一-鿿]|[^\W_]+(?:['’\-][^\W_]+)*"
)

# Elements whose text is not part of the normalised reading.
SKIP_TEXT = {"note", "abbr", "sic", "orig", "del", "fw", "figDesc", "gap", "space"}
# Elements that always separate words.
BLOCK = {
    "p", "ab", "l", "lg", "head", "div", "item", "list", "opener", "closer",
    "salute", "signed", "dateline", "postscript", "byline", "argument", "row",
    "cell", "table", "cit", "quote",
}

TOP_WORDS_PER_LANGUAGE = 25


def local(el):
    return el.tag.split("}")[-1] if isinstance(el.tag, str) else ""


def text_of(el):
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def norm_lang(code):
    """'es-419' -> 'es'. Aggregates use the primary subtag only."""
    return (code or "").strip().lower().split("-")[0]


def first(root, path):
    return root.find(path, NS)


def parse_year(value):
    m = re.match(r"\s*(-?\d{1,4})", value or "")
    return int(m.group(1)) if m else None


def ints_in(value):
    return [int(x) for x in re.findall(r"\d+", value or "")]


def segments(el, lang):
    """Yield (language, text) pieces of the normalised reading."""
    lang = el.get(XML_LANG) or lang
    tag = local(el)
    if tag in SKIP_TEXT:
        return
    block = tag in BLOCK
    if block:
        yield lang, " "
    if el.text:
        yield lang, el.text
    for child in el:
        if not isinstance(child.tag, str):
            continue
        ctag = local(child)
        if (ctag in ("lb", "cb") and child.get("break") != "no") or ctag == "pb":
            yield lang, " "
        yield from segments(child, lang)
        if child.tail:
            yield lang, child.tail
    if block:
        yield lang, " "


def analyse_text(text_el, main_lang):
    words_by_lang = Counter()
    freq = {}
    total = 0
    for raw_lang, chunk in segments(text_el, main_lang):
        lang = norm_lang(raw_lang) or norm_lang(main_lang) or "und"
        for token in TOKEN.findall(chunk):
            token = unicodedata.normalize("NFC", token.casefold())
            if token.isdigit():
                continue
            words_by_lang[lang] += 1
            freq.setdefault(lang, Counter())[token] += 1
            total += 1
    top = {
        lang: [[w, c] for w, c in counter.most_common(TOP_WORDS_PER_LANGUAGE)]
        for lang, counter in freq.items()
    }
    return total, dict(words_by_lang), top


def describe(path, warnings):
    root = ET.parse(path).getroot()
    if local(root) != "TEI":
        raise ValueError("root element is <%s>, expected <TEI>" % local(root))

    header = first(root, "t:teiHeader")
    if header is None:
        raise ValueError("no <teiHeader>")
    text_el = first(root, "t:text")
    if text_el is None:
        raise ValueError("no <text>")

    def warn(message):
        warnings.append("%s: %s" % (path.name, message))

    doc_id = root.get(XML_ID) or path.stem

    title = text_of(first(header, ".//t:titleStmt/t:title"))
    if not title:
        warn("no <title> in titleStmt")
        title = doc_id

    country = first(header, ".//t:msIdentifier/t:country")
    nation = text_of(country)
    nation_code = (country.get("key") or "") if country is not None else ""
    if not nation:
        warn("no <country> in msIdentifier (the Nation filter needs it)")
        nation = "Unspecified"
    place = text_of(first(header, ".//t:msIdentifier/t:settlement"))
    repository = text_of(first(header, ".//t:msIdentifier/t:repository"))
    shelfmark = text_of(first(header, ".//t:msIdentifier/t:idno"))

    item = first(header, ".//t:msContents/t:msItem")
    doc_type = ((item.get("class") if item is not None else "") or "").lstrip("#")
    if not doc_type:
        div = first(text_el, ".//t:div[@type]")
        doc_type = div.get("type") if div is not None else "document"
    summary = text_of(first(header, ".//t:msContents/t:summary"))

    # Languages -----------------------------------------------------------
    text_lang = first(header, ".//t:msContents//t:textLang")
    if text_lang is None:
        text_lang = first(header, ".//t:textLang")
    main = norm_lang(text_lang.get("mainLang")) if text_lang is not None else ""
    others = (
        [norm_lang(x) for x in (text_lang.get("otherLangs") or "").split()]
        if text_lang is not None
        else []
    )
    if not main:
        declared = [
            norm_lang(l.get("ident"))
            for l in header.iterfind(".//t:langUsage/t:language", NS)
        ]
        declared = [d for d in declared if d]
        if declared:
            main, others = declared[0], others + declared[1:]
    if not main:
        main = norm_lang(root.get(XML_LANG) or text_el.get(XML_LANG))
    if not main:
        warn("no language declared (textLang/@mainLang)")
        main = "und"
    others = list(dict.fromkeys(l for l in others if l and l != main))

    # Date ------------------------------------------------------------------
    date_el = first(header, ".//t:history/t:origin/t:origDate")
    if date_el is None:
        date_el = first(header, ".//t:profileDesc/t:creation/t:date")
    year = year_end = None
    date_label = ""
    if date_el is not None:
        start = (
            date_el.get("when") or date_el.get("notBefore")
            or date_el.get("from") or date_el.get("when-iso")
        )
        end = date_el.get("notAfter") or date_el.get("to")
        year = parse_year(start)
        year_end = parse_year(end) if end else year
        date_label = text_of(date_el) or " to ".join(x for x in (start, end) if x)
    if year is None:
        warn("no usable date (origDate/@when, @notBefore or @from)")
    century = (year - 1) // 100 + 1 if year and year > 0 else None
    decade = year // 10 * 10 if year and year > 0 else None

    # Physical description ----------------------------------------------
    object_desc = first(header, ".//t:physDesc/t:objectDesc")
    support_desc = first(header, ".//t:physDesc//t:supportDesc")
    layout_el = first(header, ".//t:layoutDesc/t:layout")
    columns_list = ints_in(layout_el.get("columns")) if layout_el is not None else []
    lines_list = ints_in(layout_el.get("writtenLines")) if layout_el is not None else []
    hand_notes = list(header.iterfind(".//t:handDesc/t:handNote", NS))
    scripts = list(dict.fromkeys(
        (h.get("script") or "").strip() for h in hand_notes if (h.get("script") or "").strip()
    ))

    # Rights and sources -------------------------------------------------
    licence = first(header, ".//t:publicationStmt//t:licence")
    if licence is None:
        warn("no <licence> in publicationStmt")
    source_url = ""
    for ref in header.iterfind(".//t:sourceDesc//t:ref", NS):
        target = (ref.get("target") or "").strip()
        if target.startswith(("http://", "https://")):
            source_url = target
            break
    bibl = first(header, ".//t:sourceDesc/t:bibl")
    citation = text_of(bibl)[:500]

    # Archive labels (era/event, perspective, community, catalog id) -----
    labels = {}
    for term in header.iterfind(".//t:profileDesc/t:textClass/t:keywords/t:term", NS):
        kind = (term.get("type") or "").strip()
        if kind and kind not in labels:
            labels[kind] = text_of(term)
    for required in ("era", "perspective"):
        if not labels.get(required):
            warn('no <term type="%s"> in textClass (the %s filter needs it)' % (required, required))

    contributors = []
    for resp in header.iterfind(".//t:titleStmt/t:respStmt", NS):
        name_el = resp.find("t:name", NS)
        if name_el is None:
            name_el = resp.find("t:persName", NS)
        who = text_of(name_el)
        what = text_of(resp.find("t:resp", NS))
        if who:
            contributors.append("%s (%s)" % (who, what) if what else who)

    # Text -----------------------------------------------------------------
    counts = Counter(local(e) for e in text_el.iter() if isinstance(e.tag, str))
    marginal = sum(
        1 for e in text_el.iter()
        if local(e) == "note" and "margin" in (e.get("place") or "")
    )
    words, lang_words, top_words = analyse_text(text_el, main)
    surfaces = len(list(root.iterfind(".//t:facsimile//t:surface", NS)))
    zones = len(list(root.iterfind(".//t:facsimile//t:zone", NS)))
    pages = counts["pb"] or surfaces or (1 if words else 0)
    if not counts["pb"]:
        warn("no <pb/> page breaks, so the page count is a guess")
    if not counts["lb"]:
        warn("no <lb/> line breaks, so line statistics will be empty")
    if not words:
        warn("the <text> has no readable words")

    observed = [l for l in lang_words if l != main and l not in others]
    all_langs = list(dict.fromkeys([main] + others + observed))

    features = {
        "handShifts": counts["handShift"],
        "additions": counts["add"],
        "deletions": counts["del"],
        "substitutions": counts["subst"],
        "unclear": counts["unclear"],
        "damage": counts["damage"],
        "gaps": counts["gap"],
        "supplied": counts["supplied"],
        "abbreviations": counts["abbr"],
        "corrections": counts["corr"],
        "regularizations": counts["reg"],
        "notes": counts["note"],
        "marginalNotes": marginal,
        "persNames": counts["persName"],
        "placeNames": counts["placeName"],
        "orgNames": counts["orgName"],
        "dates": counts["date"],
        "terms": counts["term"],
        "foreign": counts["foreign"],
        "stamps": counts["stamp"] + counts["seal"],
        "figures": counts["figure"],
    }

    return {
        "id": doc_id,
        "file": path.name,
        "title": title,
        "nation": nation,
        "nationCode": nation_code,
        "place": place,
        "repository": repository,
        "shelfmark": shelfmark,
        "type": doc_type,
        "summary": summary,
        "catalogId": labels.get("catalog", ""),
        "era": labels.get("era", "") or "Unassigned",
        "eraYears": labels.get("eraYears", ""),
        "perspective": labels.get("perspective", "") or "unassigned",
        "community": labels.get("community", ""),
        "languages": {"main": main, "other": others, "all": all_langs},
        "date": {"label": date_label, "year": year, "yearEnd": year_end},
        "century": century,
        "decade": decade,
        "support": {
            "form": (object_desc.get("form") or "") if object_desc is not None else "",
            "material": ((support_desc.get("material") or "") if support_desc is not None else "").lstrip("#"),
            "description": text_of(first(header, ".//t:supportDesc/t:support")),
        },
        "layout": {
            "columns": max(columns_list) if columns_list else None,
            "writtenLines": round(sum(lines_list) / len(lines_list)) if lines_list else None,
        },
        "hands": {"count": len(hand_notes), "scripts": scripts},
        "license": {
            "name": text_of(licence),
            "url": (licence.get("target") or "") if licence is not None else "",
        },
        "sourceUrl": source_url,
        "citation": citation,
        "contributors": contributors,
        "stats": {
            "pages": pages,
            "lines": counts["lb"],
            "words": words,
            "columnBreaks": counts["cb"],
            "surfaces": surfaces,
            "zones": zones,
        },
        "langWords": lang_words,
        "features": features,
        "topWords": top_words,
    }


def main():
    parser = argparse.ArgumentParser(description="Build documents-data.js from TEI-XML files.")
    parser.add_argument("--tei-dir", default="tei", help="folder of TEI-XML files (default: tei)")
    parser.add_argument("--out", default="documents-data.js", help="output file (default: documents-data.js)")
    args = parser.parse_args()

    tei_dir = Path(args.tei_dir)
    if not tei_dir.is_dir():
        sys.exit("TEI folder not found: %s" % tei_dir)

    records, warnings, errors = [], [], []
    for path in sorted(tei_dir.glob("*.xml")):
        if path.name.startswith("_"):
            continue
        try:
            records.append(describe(path, warnings))
        except (ET.ParseError, ValueError) as exc:
            errors.append("%s: %s" % (path.name, exc))

    seen = Counter(r["id"] for r in records)
    for doc_id, n in seen.items():
        if n > 1:
            errors.append("duplicate xml:id %r used by %d files" % (doc_id, n))

    records.sort(key=lambda r: (r["date"]["year"] if r["date"]["year"] is not None else 9999, r["id"]))

    body = json.dumps(records, ensure_ascii=False, indent=1)
    Path(args.out).write_text(
        "// Generated by tools/build_documents.py from the TEI-XML files in tei/.\n"
        "// Do not edit by hand; edit the TEI files and run the script again.\n"
        "window.ARCHIVE_DOCUMENTS = %s;\n" % body,
        encoding="utf-8",
    )

    nations = sorted({r["nation"] for r in records})
    languages = sorted({l for r in records for l in r["languages"]["all"]})
    print("Wrote %d documents to %s" % (len(records), args.out))
    print("  %d nations: %s" % (len(nations), ", ".join(nations) or "none"))
    print("  %d languages: %s" % (len(languages), ", ".join(languages) or "none"))
    print("  %d words, %d pages" % (
        sum(r["stats"]["words"] for r in records),
        sum(r["stats"]["pages"] for r in records),
    ))
    if warnings:
        print("\n%d warning(s):" % len(warnings))
        for w in warnings:
            print("  - " + w)
    if errors:
        print("\n%d file(s) NOT included:" % len(errors), file=sys.stderr)
        for e in errors:
            print("  - " + e, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
