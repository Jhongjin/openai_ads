const MAIL_SHEET_NAME = "openai_mail_rag";
const MAIL_SHEET_HEADERS = [
  "collected_at_kst",
  "received_at",
  "uid",
  "message_id",
  "from_name",
  "from_email",
  "to",
  "cc",
  "subject",
  "body_summary",
  "body_text",
  "attachment_names",
  "attachment_text",
  "tags",
  "rag_document_id",
  "duplicate_hash",
  "status",
  "last_embedded_at",
];

function doPost(e) {
  try {
    const payload = JSON.parse((e.postData && e.postData.contents) || "{}");
    const expectedSecret =
      PropertiesService.getScriptProperties().getProperty("MAIL_COLLECTOR_SHEETS_SHARED_SECRET") ||
      PropertiesService.getScriptProperties().getProperty("SHEETS_SHARED_SECRET");
    if (!expectedSecret || payload.secret !== expectedSecret) {
      return jsonResponse_({ ok: false, error: "unauthorized" });
    }

    const rows = normalizeRows_((payload.data && payload.data.rows) || payload.rows);
    const sheet = ensureSheet_(MAIL_SHEET_NAME, MAIL_SHEET_HEADERS);
    const existingHashes = existingHashSet_(sheet);
    const appendRows = rows.filter((row) => {
      const hash = String(row.duplicate_hash || "");
      return hash && !existingHashes.has(hash);
    });

    if (appendRows.length) {
      const values = appendRows.map((row) =>
        MAIL_SHEET_HEADERS.map((header) => {
          const value = row[header];
          if (Array.isArray(value) || (value && typeof value === "object")) {
            return JSON.stringify(value);
          }
          return value == null ? "" : value;
        }),
      );
      sheet.getRange(sheet.getLastRow() + 1, 1, values.length, MAIL_SHEET_HEADERS.length).setValues(values);
    }

    return jsonResponse_({
      ok: true,
      received: rows.length,
      appended: appendRows.length,
      skippedDuplicates: rows.length - appendRows.length,
    });
  } catch (error) {
    return jsonResponse_({ ok: false, error: String(error && error.message ? error.message : error) });
  }
}

function existingHashSet_(sheet) {
  const result = new Set();
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return result;
  const hashColumnIndex = MAIL_SHEET_HEADERS.indexOf("duplicate_hash") + 1;
  const values = sheet.getRange(2, hashColumnIndex, lastRow - 1, 1).getValues();
  values.forEach((row) => {
    const hash = String(row[0] || "");
    if (hash) result.add(hash);
  });
  return result;
}

function ensureSheet_(sheetName, headers) {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(sheetName) || spreadsheet.insertSheet(sheetName);
  const currentHeaders = sheet.getRange(1, 1, 1, headers.length).getValues()[0];
  const needsHeader = currentHeaders.every((cell) => !cell);
  if (needsHeader) {
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function normalizeRows_(rows) {
  if (!rows) return [];
  return Array.isArray(rows) ? rows : [rows];
}

function jsonResponse_(body) {
  const output = ContentService.createTextOutput(JSON.stringify(body));
  output.setMimeType(ContentService.MimeType.JSON);
  return output;
}
