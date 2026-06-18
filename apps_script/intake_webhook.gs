const SHEET_COLUMNS = {
  campaigns: [
    { key: "receipt_number", header: "접수번호" },
    { key: "campaign_name", header: "campaign_name" },
    { key: "budget_max", header: "budget_max" },
    { key: "budget_type", header: "budget_type" },
    { key: "launch_date", header: "launch_date" },
    { key: "end_date", header: "end_date" },
    { key: "objective", header: "objective" },
    { key: "target_countries", header: "target_countries" },
  ],
  adgroups: [
    { key: "receipt_number", header: "접수번호" },
    { key: "campaign_name", header: "campaign_name" },
    { key: "adgroup_name", header: "adgroup_name" },
    { key: "max_bid", header: "max_bid" },
    { key: "keywords", header: "keywords" },
  ],
  ads: [
    { key: "receipt_number", header: "접수번호" },
    { key: "adgroup_name", header: "adgroup_name" },
    { key: "title", header: "title" },
    { key: "copy", header: "copy" },
    { key: "link", header: "link" },
    { key: "image_link", header: "image_link" },
  ],
  ops_meta: [
    { key: "receipt_number", header: "접수번호" },
    { key: "submitted_at_kst", header: "제출시각(KST)" },
    { key: "route", header: "집행경로" },
    { key: "advertiser_name", header: "광고주명" },
    { key: "legal_name", header: "법인정식명칭" },
    { key: "brn", header: "BRN" },
    { key: "homepage", header: "광고주공식홈페이지" },
    { key: "invoice_email", header: "인보이스이메일" },
    { key: "contact_name", header: "광고주담당자명" },
    { key: "contact_phone", header: "광고주연락처" },
    { key: "contact_email", header: "광고주이메일" },
    { key: "sales_owner", header: "케이티나스미디어영업담당자" },
    { key: "ready_ads_manager", header: "AdsManager생성" },
    { key: "ready_payment", header: "결제수단등록" },
    { key: "ready_crawler", header: "크롤러점검완료" },
    { key: "ready_favicon", header: "파비콘준비" },
    { key: "note", header: "비고" },
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
    const campaigns = normalizeRows_(data.campaigns || data.campaign);
    const adgroups = normalizeRows_(data.adgroups);
    const ads = normalizeRows_(data.ads);
    const ops = data.ops || {};

    if (!campaigns.length) {
      return jsonResponse_({ ok: false, error: "campaigns is required" });
    }

    const lock = LockService.getScriptLock();
    lock.waitLock(10000);
    try {
      const receiptNumber = nextReceiptNumber_();
      const submittedAtKst = nowKst_();
      const withReceipt = (row) => Object.assign({ receipt_number: receiptNumber }, row);
      const adgroupsForSheet = adgroups.map((row) => Object.assign({}, row, {
        campaign_name: row.campaign_name || campaigns[0].campaign_name || "",
      }));

      const opsMeta = Object.assign({}, ops, {
        receipt_number: receiptNumber,
        submitted_at_kst: submittedAtKst,
      });

      appendRows_("campaigns", campaigns.map(withReceipt));
      appendRows_("adgroups", adgroupsForSheet.map(withReceipt));
      appendRows_("ads", ads.map(withReceipt));
      appendRows_("ops_meta", [opsMeta]);

      notifyOps_(receiptNumber, submittedAtKst, ops, campaigns, adgroups, ads);

      return jsonResponse_({
        ok: true,
        receiptNumber,
        submittedAtKst,
        counts: {
          campaigns: campaigns.length,
          adgroups: adgroups.length,
          ads: ads.length,
        },
      });
    } finally {
      lock.releaseLock();
    }
  } catch (error) {
    return jsonResponse_({ ok: false, error: String(error && error.message ? error.message : error) });
  }
}

function appendRows_(sheetName, rows) {
  if (!rows.length) return;
  const columns = SHEET_COLUMNS[sheetName];
  const sheet = ensureSheet_(sheetName, columns);
  const values = rows.map((row) =>
    columns.map((column) => {
      const value = row[column.key];
      if (Array.isArray(value) || (value && typeof value === "object")) {
        return JSON.stringify(value);
      }
      return value == null ? "" : value;
    }),
  );
  sheet.getRange(sheet.getLastRow() + 1, 1, values.length, columns.length).setValues(values);
}

function ensureSheet_(sheetName, columns) {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(sheetName) || spreadsheet.insertSheet(sheetName);
  const headers = columns.map((column) => column.header);
  const currentHeaders = sheet.getRange(1, 1, 1, Math.max(headers.length, sheet.getLastColumn() || headers.length)).getValues()[0];
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

function notifyOps_(receiptNumber, submittedAtKst, ops, campaigns, adgroups, ads) {
  const recipient = "openai@nasmedia.co.kr";
  const subject = `[OpenAI Ads 접수] ${receiptNumber} · ${ops.advertiser_name || "광고주명 없음"}`;
  const body = [
    `접수번호: ${receiptNumber}`,
    `제출시각(KST): ${submittedAtKst}`,
    `광고주명: ${ops.advertiser_name || ""}`,
    `법인명: ${ops.legal_name || ""}`,
    `집행경로: ${ops.route || ""}`,
    `캠페인 수: ${campaigns.length}`,
    `광고그룹 수: ${adgroups.length}`,
    `소재 수: ${ads.length}`,
    "",
    "캠페인 목록:",
    ...campaigns.map((campaign) => `- ${campaign.campaign_name || ""} / ${campaign.objective || ""} / ${campaign.budget_max || ""}`),
  ].join("\n");

  try {
    MailApp.sendEmail(recipient, subject, body);
  } catch (error) {
    console.log(`MailApp.sendEmail failed: ${error}`);
  }
}

function jsonResponse_(body) {
  const output = ContentService.createTextOutput(JSON.stringify(body));
  output.setMimeType(ContentService.MimeType.JSON);
  return output;
}
