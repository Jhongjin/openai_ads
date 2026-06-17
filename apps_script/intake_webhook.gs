const SHEET_HEADERS = {
  campaigns: [
    "campaign_name",
    "budget_max",
    "budget_type",
    "launch_date",
    "end_date",
    "objective",
    "target_countries",
  ],
  adgroups: ["campaign_name", "adgroup_name", "max_bid", "keywords"],
  ads: ["adgroup_name", "title", "copy", "link", "image_link"],
  ops_meta: [
    "receipt_number",
    "submitted_at_kst",
    "campaign_name",
    "route",
    "advertiser_name",
    "legal_name",
    "brn",
    "homepage",
    "invoice_email",
    "contact_name",
    "contact_phone",
    "contact_email",
    "sales_owner",
    "ready_ads_manager",
    "ready_payment",
    "ready_crawler",
    "ready_favicon",
    "note",
  ],
};

function doPost(e) {
  try {
    const payload = JSON.parse((e.postData && e.postData.contents) || "{}");
    const expectedSecret = PropertiesService.getScriptProperties().getProperty("SHEETS_SHARED_SECRET");
    if (!expectedSecret || payload.secret !== expectedSecret) {
      return jsonResponse_({ ok: false, error: "unauthorized" });
    }

    const data = payload.data || {};
    const campaign = data.campaign || {};
    const adgroups = normalizeRows_(data.adgroups).map((row) =>
      Object.assign({ campaign_name: campaign.campaign_name || "" }, row),
    );
    const ads = normalizeRows_(data.ads);
    const ops = data.ops || {};

    const lock = LockService.getScriptLock();
    lock.waitLock(10000);
    try {
      const receiptNumber = nextReceiptNumber_();
      const submittedAtKst = nowKst_();
      const opsMeta = Object.assign({}, ops, {
        receipt_number: receiptNumber,
        submitted_at_kst: submittedAtKst,
        campaign_name: campaign.campaign_name || "",
      });

      appendRows_("campaigns", [campaign]);
      appendRows_("adgroups", adgroups);
      appendRows_("ads", ads);
      appendRows_("ops_meta", [opsMeta]);

      return jsonResponse_({ ok: true, receiptNumber, submittedAtKst });
    } finally {
      lock.releaseLock();
    }
  } catch (error) {
    return jsonResponse_({ ok: false, error: String(error && error.message ? error.message : error) });
  }
}

function appendRows_(sheetName, rows) {
  if (!rows.length) return;
  const sheet = ensureSheet_(sheetName, SHEET_HEADERS[sheetName]);
  const values = rows.map((row) =>
    SHEET_HEADERS[sheetName].map((header) => {
      const value = row[header];
      if (Array.isArray(value) || (value && typeof value === "object")) {
        return JSON.stringify(value);
      }
      return value == null ? "" : value;
    }),
  );
  sheet.getRange(sheet.getLastRow() + 1, 1, values.length, SHEET_HEADERS[sheetName].length).setValues(values);
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

function nextReceiptNumber_() {
  const properties = PropertiesService.getScriptProperties();
  const day = Utilities.formatDate(new Date(), "Asia/Seoul", "yyyyMMdd");
  const key = `RECEIPT_COUNTER_${day}`;
  const next = Number(properties.getProperty(key) || "0") + 1;
  properties.setProperty(key, String(next));
  return `KT-OAI-${day}-${String(next).padStart(3, "0")}`;
}

function nowKst_() {
  return Utilities.formatDate(new Date(), "Asia/Seoul", "yyyy-MM-dd HH:mm:ss");
}

function jsonResponse_(body) {
  const output = ContentService.createTextOutput(JSON.stringify(body));
  output.setMimeType(ContentService.MimeType.JSON);
  return output;
}
