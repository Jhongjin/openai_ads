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
    { key: "ad_name", header: "ad_name" },
    { key: "title", header: "title" },
    { key: "copy", header: "copy" },
    { key: "link", header: "link" },
    { key: "image_link", header: "image_link" },
  ],
  ops_meta: [
    { key: "receipt_number", header: "접수번호" },
    { key: "submitted_at_kst", header: "제출시각" },
    { key: "advertiser_name", header: "광고주명" },
    { key: "brand_name", header: "브랜드명" },
    { key: "sales_owner", header: "담당자명" },
    { key: "sales_owner_email", header: "담당자 이메일" },
    { key: "owner_headquarters", header: "본부" },
    { key: "owner_office", header: "실" },
    { key: "owner_team", header: "팀" },
    { key: "note", header: "비고" },
  ],
  settings: [
    { key: "receipt_number", header: "접수번호" },
    { key: "submitted_at_kst", header: "제출시각" },
    { key: "advertiser_name", header: "광고주" },
    { key: "sales_owner", header: "담당자" },
    { key: "owner_department", header: "소속" },
    { key: "operator_name", header: "운영자" },
    { key: "status_label", header: "상태" },
    { key: "memo", header: "운영 메모" },
  ],
};

const SETTING_STATUS_LABELS = {
  ready: "대기",
  in_progress: "진행중",
  done: "완료",
  canceled: "취소",
};

function doPost(e) {
  try {
    const payload = JSON.parse((e.postData && e.postData.contents) || "{}");
    const expectedSecret = PropertiesService.getScriptProperties().getProperty("SHEETS_SHARED_SECRET");
    if (!expectedSecret || payload.secret !== expectedSecret) {
      return jsonResponse_({ ok: false, error: "unauthorized" });
    }

    if (payload.action === "campaign_intake_list") {
      return jsonResponse_(campaignIntakeList_(payload));
    }

    if (payload.action === "campaign_intake_settings_update") {
      return jsonResponse_(updateCampaignIntakeSetting_(payload));
    }

    const data = payload.data || {};
    const campaigns = normalizeRows_(data.campaigns || data.campaign_rows || data.campaign);
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
      const fallbackCampaignName = campaigns.length === 1 ? campaigns[0].campaign_name || "" : "";
      const adgroupsForSheet = adgroups.map((row) => Object.assign({}, row, {
        campaign_name: row.campaign_name || fallbackCampaignName,
      }));

      const missingCampaignNameAdgroup = adgroupsForSheet.find((row) => !row.campaign_name);
      if (missingCampaignNameAdgroup) {
        return jsonResponse_({
          ok: false,
          error: `adgroup "${missingCampaignNameAdgroup.adgroup_name || ""}" has no campaign_name`,
        });
      }

      const opsMeta = Object.assign({}, ops, {
        receipt_number: receiptNumber,
        submitted_at_kst: submittedAtKst,
      });

      appendRows_("campaigns", campaigns.map(withReceipt));
      appendRows_("adgroups", adgroupsForSheet.map(withReceipt));
      appendRows_("ads", ads.map(withReceipt));
      appendRows_("ops_meta", [opsMeta]);
      upsertSettingRow_(buildSettingRow_(receiptNumber, submittedAtKst, ops, "", "ready", ""));

      const mailResult = notifyOps_(receiptNumber, submittedAtKst, ops, campaigns, adgroups, ads);

      return jsonResponse_({
        ok: true,
        receiptNumber,
        submittedAtKst,
        mailSent: mailResult.sent,
        mailError: mailResult.error || "",
        mailSender: mailResult.sender || "",
        mailRecipient: mailResult.recipient || "",
        mailCc: mailResult.cc || "",
        mailQuotaRemaining: mailResult.quotaRemaining,
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
  const values = rows.map((row) => rowValues_(columns, row));
  sheet.getRange(sheet.getLastRow() + 1, 1, values.length, columns.length).setValues(values);
}

function rowValues_(columns, row) {
  return columns.map((column) => {
    const value = row[column.key];
    if (Array.isArray(value) || (value && typeof value === "object")) {
      return JSON.stringify(value);
    }
    return value == null ? "" : value;
  });
}

function campaignIntakeList_() {
  return {
    ok: true,
    sheets: {
      campaigns: readSheetRows_("campaigns"),
      adgroups: readSheetRows_("adgroups"),
      ads: readSheetRows_("ads"),
      ops_meta: readSheetRows_("ops_meta"),
      settings: readSheetRows_("settings"),
    },
  };
}

function updateCampaignIntakeSetting_(payload) {
  const setting = payload.setting || {};
  const receiptNumber = String(setting.receipt_number || setting.receiptNumber || "").trim();
  if (!receiptNumber) {
    return { ok: false, error: "receipt_number is required" };
  }

  const updated = upsertSettingRow_({
    receipt_number: receiptNumber,
    operator_name: setting.operator_name || "",
    status_label: statusLabel_(setting.status || setting.status_label || setting.statusLabel || "ready"),
    memo: setting.memo || "",
  });
  return { ok: true, row: updated.row, receiptNumber };
}

function upsertSettingRow_(setting) {
  const columns = SHEET_COLUMNS.settings;
  const sheet = ensureSheet_("settings", columns);
  const receiptNumber = String(setting.receipt_number || "").trim();
  const existing = findSettingRow_(sheet, receiptNumber);
  const merged = Object.assign({}, existing.item || {}, setting);
  if (setting.status || setting.status_label || setting.statusLabel) {
    merged.status_label = statusLabel_(setting.status || setting.status_label || setting.statusLabel);
  }
  const values = rowValues_(columns, merged);
  if (existing.row > 0) {
    sheet.getRange(existing.row, 1, 1, columns.length).setValues([values]);
    return { row: existing.row, item: merged };
  }
  const nextRow = sheet.getLastRow() + 1;
  sheet.getRange(nextRow, 1, 1, columns.length).setValues([values]);
  return { row: nextRow, item: merged };
}

function findSettingRow_(sheet, receiptNumber) {
  const columns = SHEET_COLUMNS.settings;
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return { row: 0, item: null };
  const values = sheet.getRange(2, 1, lastRow - 1, columns.length).getValues();
  for (let index = 0; index < values.length; index += 1) {
    const item = {};
    columns.forEach((column, columnIndex) => {
      item[column.key] = normalizeSheetCell_(values[index][columnIndex]);
    });
    if (String(item.receipt_number || "").trim() === receiptNumber) {
      return { row: index + 2, item };
    }
  }
  return { row: 0, item: null };
}

function buildSettingRow_(receiptNumber, submittedAtKst, ops, operatorName, status, memo) {
  return {
    receipt_number: receiptNumber,
    submitted_at_kst: submittedAtKst,
    advertiser_name: ops.advertiser_name || "",
    sales_owner: ops.sales_owner || "",
    owner_department: ownerDepartment_(ops),
    operator_name: operatorName || "",
    status_label: statusLabel_(status),
    memo: memo || "",
  };
}

function ownerDepartment_(ops) {
  return [ops.owner_headquarters, ops.owner_office, ops.owner_team]
    .map((item) => String(item || "").trim())
    .filter(Boolean)
    .join(" / ");
}

function statusLabel_(status) {
  const raw = String(status || "").trim();
  if (SETTING_STATUS_LABELS[raw]) return SETTING_STATUS_LABELS[raw];
  if (Object.keys(SETTING_STATUS_LABELS).some((key) => SETTING_STATUS_LABELS[key] === raw)) return raw;
  return SETTING_STATUS_LABELS.ready;
}

function readSheetRows_(sheetName) {
  const columns = SHEET_COLUMNS[sheetName];
  const sheet = ensureSheet_(sheetName, columns);
  const lastRow = sheet.getLastRow();
  const lastColumn = sheet.getLastColumn();
  if (lastRow < 2 || lastColumn < 1) return [];

  const keyByHeader = {};
  columns.forEach((column) => {
    keyByHeader[column.header] = column.key;
    keyByHeader[column.key] = column.key;
  });
  const headers = sheet
    .getRange(1, 1, 1, lastColumn)
    .getValues()[0]
    .map((value) => String(value || "").trim());
  const values = sheet.getRange(2, 1, lastRow - 1, lastColumn).getValues();

  return values
    .map((row, rowIndex) => {
      const item = { __row: rowIndex + 2 };
      headers.forEach((header, index) => {
        if (!header) return;
        const key = keyByHeader[header] || header;
        item[key] = normalizeSheetCell_(row[index]);
      });
      return item;
    })
    .filter((item) => {
      return Object.keys(item).some((key) => key !== "__row" && String(item[key] || "").trim());
    });
}

function normalizeSheetCell_(value) {
  if (value instanceof Date) {
    return Utilities.formatDate(value, "Asia/Seoul", "yyyy-MM-dd HH:mm:ss");
  }
  if (Array.isArray(value) || (value && typeof value === "object")) {
    return JSON.stringify(value);
  }
  return value == null ? "" : String(value).trim();
}

function ensureSheet_(sheetName, columns) {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(sheetName) || spreadsheet.insertSheet(sheetName);
  const headers = columns.map((column) => column.header);
  const existingHeaderCount = sheet.getLastColumn();
  const existingHeaders = existingHeaderCount
    ? sheet.getRange(1, 1, 1, existingHeaderCount).getValues()[0].map((value) => String(value || "").trim())
    : [];

  headers.forEach((header, index) => {
    if (existingHeaders[index] === header) return;
    if (existingHeaders.indexOf(header, index + 1) === -1) {
      sheet.insertColumnBefore(index + 1);
      existingHeaders.splice(index, 0, header);
    }
  });

  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  sheet.setFrozenRows(1);
  if ((sheetName === "ops_meta" || sheetName === "settings") && sheet.getMaxColumns() > headers.length) {
    sheet.deleteColumns(headers.length + 1, sheet.getMaxColumns() - headers.length);
  }
  if (sheetName === "settings") {
    const statusRule = SpreadsheetApp.newDataValidation()
      .requireValueInList(Object.keys(SETTING_STATUS_LABELS).map((key) => SETTING_STATUS_LABELS[key]), true)
      .setAllowInvalid(false)
      .build();
    sheet.getRange(2, 7, Math.max(1, sheet.getMaxRows() - 1), 1).setDataValidation(statusRule);
  }
  return sheet;
}

function syncHeadersNow() {
  Object.keys(SHEET_COLUMNS).forEach((sheetName) => {
    ensureSheet_(sheetName, SHEET_COLUMNS[sheetName]);
  });
}

function syncOpsMetaHeaderNow() {
  ensureSheet_("ops_meta", SHEET_COLUMNS.ops_meta);
}

function syncSettingsHeaderNow() {
  ensureSheet_("settings", SHEET_COLUMNS.settings);
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
  const properties = PropertiesService.getScriptProperties();
  const recipient = properties.getProperty("NOTIFY_TO") || "openai@nasmedia.co.kr";
  const sheetUrl = properties.getProperty("INTAKE_SHEET_URL") || "https://docs.google.com/spreadsheets/d/1OvzkaxDXtCRBZZHOs8_gNJjqA093XNKlZTJdQfLxVII/edit?gid=1219574566#gid=1219574566";
  const sender = getMailSender_();
  const configuredCc = (properties.getProperty("NOTIFY_CC") || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const ccList = uniqueEmails_([
    ops.sales_owner_email,
    ...configuredCc,
  ]).filter((email) => email.toLowerCase() !== recipient.toLowerCase());
  const subject = `[OpenAI Ads 접수] ${receiptNumber} · ${ops.advertiser_name || "광고주명 없음"}`;
  const body = [
    `접수번호: ${receiptNumber}`,
    `제출시각: ${submittedAtKst}`,
    `광고주명: ${ops.advertiser_name || ""}`,
    `브랜드명: ${ops.brand_name || ""}`,
    `담당자명: ${ops.sales_owner || ""} / ${ops.sales_owner_email || ""}`,
    `소속: ${ops.owner_headquarters || ""} / ${ops.owner_office || ""} / ${ops.owner_team || ""}`,
    `캠페인 수: ${campaigns.length}`,
    `광고그룹 수: ${adgroups.length}`,
    `소재 수: ${ads.length}`,
    `발송 실행 계정: ${sender || "확인 불가"}`,
    "",
    "캠페인 목록:",
    ...campaigns.map((campaign) => `- ${campaign.campaign_name || ""} / ${campaign.objective || ""} / ${campaign.budget_max || ""}`),
    "",
    `구글 시트 바로가기: ${sheetUrl}`,
  ].join("\n");
  const htmlBody = buildNotificationHtml_(receiptNumber, submittedAtKst, ops, campaigns, adgroups, ads, sender, sheetUrl);

  try {
    const quotaRemaining = MailApp.getRemainingDailyQuota();
    const options = {
      name: "OpenAI Ads 접수 알림",
      replyTo: ops.sales_owner_email || recipient,
      htmlBody,
    };
    if (ccList.length) {
      options.cc = ccList.join(",");
    }
    MailApp.sendEmail(recipient, subject, body, options);
    return { sent: true, error: "", sender, recipient, cc: ccList.join(","), quotaRemaining };
  } catch (error) {
    const message = String(error && error.message ? error.message : error);
    Logger.log(`MailApp.sendEmail failed: ${message}`);
    return { sent: false, error: message, sender, recipient, cc: ccList.join(","), quotaRemaining: null };
  }
}

function buildNotificationHtml_(receiptNumber, submittedAtKst, ops, campaigns, adgroups, ads, sender, sheetUrl) {
  const campaignRows = campaigns.map((campaign, index) => `
    <tr>
      <td style="padding:12px 10px;border-top:1px solid #e5e7eb;color:#6b7280;font-size:13px;">${index + 1}</td>
      <td style="padding:12px 10px;border-top:1px solid #e5e7eb;color:#111827;font-size:14px;font-weight:700;">${escapeHtml_(campaign.campaign_name)}</td>
      <td style="padding:12px 10px;border-top:1px solid #e5e7eb;color:#111827;font-size:14px;">${formatObjective_(campaign.objective)}</td>
      <td style="padding:12px 10px;border-top:1px solid #e5e7eb;color:#111827;font-size:14px;text-align:right;">${formatBudget_(campaign.budget_max)}</td>
    </tr>
  `).join("");

  return `
    <div style="margin:0;padding:0;background:#f5f6f8;font-family:Arial,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;color:#111827;">
      <div style="max-width:720px;margin:0 auto;padding:28px 16px;">
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:18px;overflow:hidden;box-shadow:0 8px 28px rgba(17,24,39,0.08);">
          <div style="padding:24px 28px 20px;border-left:6px solid #ed1c24;">
            <div style="font-size:13px;color:#ed1c24;font-weight:800;letter-spacing:.02em;">OpenAI Ads 접수 알림</div>
            <h1 style="margin:8px 0 6px;font-size:24px;line-height:1.35;color:#111827;">광고 소재 업로드 요청이 접수되었습니다</h1>
            <p style="margin:0;color:#6b7280;font-size:14px;line-height:1.6;">구글 시트에 기록이 완료되었습니다. 캠페인명, 광고그룹명, 소재 URL을 확인해 주세요.</p>
          </div>

          <div style="padding:0 28px 24px;">
            <div style="background:#fff5f5;border:1px solid #fecaca;border-radius:14px;padding:16px 18px;margin:0 0 18px;">
              <div style="font-size:12px;color:#991b1b;font-weight:800;margin-bottom:4px;">접수번호</div>
              <div style="font-size:22px;line-height:1.35;color:#111827;font-weight:800;">${escapeHtml_(receiptNumber)}</div>
              <div style="font-size:13px;color:#6b7280;margin-top:6px;">${escapeHtml_(submittedAtKst)} KST</div>
            </div>

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;margin:0 0 18px;">
              <tr>
                ${summaryCard_("캠페인", campaigns.length)}
                ${summaryCard_("광고그룹", adgroups.length)}
                ${summaryCard_("소재", ads.length)}
              </tr>
            </table>

            <div style="border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;margin-bottom:18px;">
              ${infoRow_("광고주명", ops.advertiser_name)}
              ${infoRow_("브랜드명", ops.brand_name || "-")}
              ${infoRow_("담당자", `${ops.sales_owner || "-"} / ${ops.sales_owner_email || "-"}`)}
              ${infoRow_("소속", `${ops.owner_headquarters || "-"} / ${ops.owner_office || "-"} / ${ops.owner_team || "-"}`)}
            </div>

            <h2 style="margin:0 0 10px;font-size:16px;color:#111827;">캠페인 목록</h2>
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;">
              <thead>
                <tr style="background:#111827;">
                  <th align="left" style="padding:11px 10px;color:#ffffff;font-size:12px;">#</th>
                  <th align="left" style="padding:11px 10px;color:#ffffff;font-size:12px;">캠페인명</th>
                  <th align="left" style="padding:11px 10px;color:#ffffff;font-size:12px;">목표</th>
                  <th align="right" style="padding:11px 10px;color:#ffffff;font-size:12px;">예산</th>
                </tr>
              </thead>
              <tbody>
                ${campaignRows || `<tr><td colspan="4" style="padding:14px;color:#6b7280;font-size:14px;">캠페인 정보가 없습니다.</td></tr>`}
              </tbody>
            </table>

            <div style="margin-top:18px;padding:14px 16px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:14px;color:#4b5563;font-size:13px;line-height:1.65;">
              발송 실행 계정: ${escapeHtml_(sender || "확인 불가")}<br>
              문의: 케이티나스미디어 미디어채널실 / openai@nasmedia.co.kr
            </div>

            <div style="margin-top:18px;text-align:left;">
              <a href="${escapeHtml_(sheetUrl)}" style="display:inline-block;background:#111827;color:#ffffff;text-decoration:none;border-radius:12px;padding:12px 18px;font-size:14px;font-weight:800;">구글 시트 바로가기</a>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function summaryCard_(label, value) {
  return `
    <td style="width:33.333%;padding:0 6px 0 0;">
      <div style="border:1px solid #e5e7eb;border-radius:14px;padding:14px 16px;background:#ffffff;">
        <div style="font-size:12px;color:#6b7280;font-weight:700;">${escapeHtml_(label)}</div>
        <div style="font-size:24px;color:#111827;font-weight:900;line-height:1.2;margin-top:4px;">${escapeHtml_(value)}</div>
      </div>
    </td>
  `;
}

function infoRow_(label, value) {
  return `
    <div style="display:block;padding:12px 16px;border-top:1px solid #e5e7eb;">
      <span style="display:inline-block;width:120px;color:#6b7280;font-size:13px;font-weight:800;">${escapeHtml_(label)}</span>
      <span style="color:#111827;font-size:14px;font-weight:600;">${escapeHtml_(value || "-")}</span>
    </div>
  `;
}

function formatObjective_(objective) {
  const normalized = String(objective || "").toLowerCase();
  if (normalized === "views") return "Views = CPM";
  if (normalized === "clicks") return "Clicks = CPC";
  return escapeHtml_(objective || "-");
}

function formatBudget_(value) {
  const raw = String(value || "").replace(/[^\d.-]/g, "");
  const number = Number(raw);
  if (!raw || Number.isNaN(number)) return escapeHtml_(value || "-");
  return `${number.toLocaleString("ko-KR")}원`;
}

function escapeHtml_(value) {
  return String(value === null || value === undefined ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function getMailSender_() {
  try {
    const effectiveUser = Session.getEffectiveUser().getEmail();
    const activeUser = Session.getActiveUser().getEmail();
    if (effectiveUser && activeUser && effectiveUser !== activeUser) {
      return `${effectiveUser} (active: ${activeUser})`;
    }
    return effectiveUser || activeUser || "";
  } catch (error) {
    return "";
  }
}

function uniqueEmails_(emails) {
  const seen = {};
  return emails
    .map((email) => String(email || "").trim())
    .filter((email) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email))
    .filter((email) => {
      const key = email.toLowerCase();
      if (seen[key]) return false;
      seen[key] = true;
      return true;
    });
}

function sendMailAuthTest() {
  const properties = PropertiesService.getScriptProperties();
  const recipient = properties.getProperty("NOTIFY_TO") || "openai@nasmedia.co.kr";
  const sender = getMailSender_();
  const configuredCc = (properties.getProperty("NOTIFY_CC") || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const ccList = uniqueEmails_(configuredCc)
    .filter((email) => email.toLowerCase() !== recipient.toLowerCase());
  const options = {
    name: "OpenAI Ads 접수 알림",
  };
  if (ccList.length) {
    options.cc = ccList.join(",");
  }
  const quotaRemaining = MailApp.getRemainingDailyQuota();
  MailApp.sendEmail(
    recipient,
    "[OpenAI Ads] Apps Script 메일 권한 테스트",
    `이 메일이 도착하면 Apps Script MailApp 권한과 발송 설정이 정상입니다.\n\n발송 실행 계정: ${sender || "확인 불가"}\nTo: ${recipient}\nCC: ${ccList.join(",") || "-"}\n남은 MailApp 쿼터: ${quotaRemaining}\n발송시각: ${nowKst_()} KST`,
    options
  );
  Logger.log(`Mail auth test sender ${sender || "-"} sent to ${recipient}${ccList.length ? ` cc ${ccList.join(",")}` : ""}; quota ${quotaRemaining}`);
}

function debugMailConfig() {
  const properties = PropertiesService.getScriptProperties();
  const recipient = properties.getProperty("NOTIFY_TO") || "openai@nasmedia.co.kr";
  const cc = properties.getProperty("NOTIFY_CC") || "";
  const sender = getMailSender_();
  const quotaRemaining = MailApp.getRemainingDailyQuota();
  Logger.log(`Mail sender/effective user=${sender || "-"}`);
  Logger.log(`NOTIFY_TO=${recipient}`);
  Logger.log(`NOTIFY_CC=${cc || "-"}`);
  Logger.log(`MailApp remaining daily quota=${quotaRemaining}`);
}

function jsonResponse_(body) {
  const output = ContentService.createTextOutput(JSON.stringify(body));
  output.setMimeType(ContentService.MimeType.JSON);
  return output;
}
