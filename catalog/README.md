# Document catalog

`catalog.csv` lists the 301 public-domain 19th-century documents chosen for transcription:
eight nations, grouped by era or event, with priority given to the voices of displaced communities.
Open it in Excel, Numbers or Google Sheets, and update `status` as each document moves along.

## Workflow

1. Pick rows (start with `priority` 1) and download the scan from `source_url`.
2. Transcribe into `tei/<id>.xml`, starting from `tei/_template.xml`. Copy `id`, `era`, `era_years`,
   `perspective` and `community` from the row into the `<textClass>` terms.
3. Run `python3 tools/build_documents.py`, check the warnings, and upload.
4. Set `status` to `transcribed`, then `checked` (after a second reader), then `published`.

## Columns

| Column | Meaning |
| --- | --- |
| `id` | Catalog number. Use it as the TEI `xml:id` and file name. |
| `nation`, `era`, `era_years` | Present-day nation and the historical era or event. |
| `title`, `item_ref` | The document and where it sits in the source (chapter, letter, page, date). |
| `source`, `author`, `year`, `language` | The published or archival source. `language` is the ISO 639 code of the text to transcribe. |
| `perspective` | Whose voice: `community`, `community-recorded` (narrated by a community member, written down by an outsider), `co-national`, `witness`, `settler`, `official`, `legislator`, `missionary`, `traveller`, `explorer`, `press`. |
| `priority` | 1 = transcribe first (community voices and the clearest accounts of displacement). |
| `link_check` | `opened`: the link was opened and the source confirmed. `found`: the link came from a search result but was not opened. `scan-to-locate`: no free scan has been found yet. |
| `item_check` | `toc`: the item was confirmed from the source's table of contents. `section-tbc`, `topic-tbc`, `date-tbc`, `source-tbc`: choose or confirm when the scan is opened. |
| `rights` | Copyright basis and anything to check before publishing. |

## Notes on balance

Most surviving 19th-century records about these communities were written by outsiders. About a
fifth of the catalog (67 rows) is in community or fellow-national voices. The `perspective` label
keeps the difference visible on the site.
