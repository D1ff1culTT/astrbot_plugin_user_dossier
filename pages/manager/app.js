/**
 * 用户档案管理页面。
 *
 * 通过 Dashboard 注入的 bridge（window.AstrBotPluginView / AstrBotPluginPage）
 * 与插件后端 Web API 通信。兼容 AstrBot 4.26+ 的旧 bridge 名称。
 */

const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;

const LIST_FIELDS = [
  { key: "basic_info", label: "基础信息", placeholder: "例如：性别：男" },
  { key: "preferences", label: "喜好与性格", placeholder: "例如：喜欢吃川菜" },
  { key: "task_preferences", label: "事务偏好", placeholder: "例如：回答先给结论" },
  { key: "lessons", label: "经验教训", placeholder: "例如：不要用列表回答" },
  { key: "notes", label: "明确要求", placeholder: "例如：称呼我为小明" },
];

const state = {
  profiles: [],
  keyword: "",
  current: null, // { platform, user_id }
  draft: null,
  settings: null,
};

const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ 基础工具

async function apiGet(endpoint, params) {
  return bridge.apiGet(endpoint, params || {});
}

async function apiPost(endpoint, body) {
  return bridge.apiPost(endpoint, body || {});
}

let toastTimer = null;

function showToast(message, type = "info") {
  const toast = $("toast");
  toast.textContent = message;
  toast.className = `toast ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add("hidden"), 3200);
}

function handleError(error) {
  console.error(error);
  showToast((error && error.message) || "操作失败", "error");
}

function buttonBusy(button, busy) {
  if (!button) return;
  button.disabled = busy;
}

function entryCount(profile) {
  let total = 0;
  for (const field of LIST_FIELDS) {
    const value = profile[field.key];
    if (Array.isArray(value)) total += value.length;
  }
  const summary = profile.status && profile.status.summary;
  return total + (summary ? 1 : 0);
}

// ------------------------------------------------------------------ 档案列表

async function loadProfiles() {
  const data = await apiGet("profiles");
  state.profiles = Array.isArray(data.profiles) ? data.profiles : [];
  $("summary").textContent = `共 ${state.profiles.length} 份档案`;
  renderList();
}

function renderList() {
  const list = $("profile-list");
  const empty = $("list-empty");
  const keyword = state.keyword.trim().toLowerCase();

  const items = state.profiles.filter((item) => {
    if (!keyword) return true;
    const name = String(item.display_name || "").toLowerCase();
    const id = String(item.user_id || "").toLowerCase();
    return name.includes(keyword) || id.includes(keyword);
  });

  list.textContent = "";
  if (items.length === 0) {
    empty.textContent = state.profiles.length === 0 ? "还没有任何档案" : "没有匹配的档案";
    empty.classList.remove("hidden");
  } else {
    empty.classList.add("hidden");
  }

  for (const item of items) {
    const li = document.createElement("li");
    li.className = "profile-item";
    if (
      state.current &&
      state.current.platform === item.platform &&
      state.current.user_id === item.user_id
    ) {
      li.classList.add("active");
    }

    const name = document.createElement("div");
    name.className = "profile-name";
    name.textContent = item.display_name || `用户 ${item.user_id}`;

    const meta = document.createElement("div");
    meta.className = "profile-meta";
    meta.textContent = `${item.platform} · ${item.entries} 条 · ${item.updated_at || "未知"}`;

    li.append(name, meta);
    li.addEventListener("click", () => {
      openProfile(item).catch(handleError);
    });
    list.appendChild(li);
  }
}

// ------------------------------------------------------------------ 档案详情

async function openProfile(item) {
  const data = await apiGet("profile", {
    platform: item.platform,
    user_id: item.user_id,
  });
  state.current = { platform: item.platform, user_id: item.user_id };
  state.draft = normalizeDraft(data.profile);
  renderList();
  renderEditor();
}

function normalizeDraft(profile) {
  const draft = {
    display_name: profile.display_name || "",
    status: (profile.status && profile.status.summary) || "",
    updated_at: profile.updated_at || "",
    created_at: profile.created_at || "",
  };
  for (const field of LIST_FIELDS) {
    const value = profile[field.key];
    draft[field.key] = Array.isArray(value) ? value.map((entry) => String(entry)) : [];
  }
  return draft;
}

function buildPayload() {
  const payload = {
    display_name: state.draft.display_name.trim(),
    status: { summary: state.draft.status.trim(), updated_at: "" },
  };
  for (const field of LIST_FIELDS) {
    payload[field.key] = state.draft[field.key]
      .map((entry) => entry.trim())
      .filter((entry) => entry.length > 0);
  }
  return payload;
}

function renderEditor() {
  const root = $("editor");
  root.textContent = "";

  if (!state.draft || !state.current) {
    const placeholder = document.createElement("div");
    placeholder.className = "placeholder";
    placeholder.textContent = "在左侧选择一位用户，查看或编辑其档案";
    root.appendChild(placeholder);
    return;
  }

  root.appendChild(renderHead());
  root.appendChild(renderStatus());
  for (const field of LIST_FIELDS) {
    root.appendChild(renderFieldSection(field));
  }
  root.appendChild(renderFoot());
}

function renderHead() {
  const head = document.createElement("div");
  head.className = "editor-head";

  const nameInput = document.createElement("input");
  nameInput.className = "input name-input";
  nameInput.placeholder = "用户昵称";
  nameInput.value = state.draft.display_name;
  nameInput.addEventListener("input", () => {
    state.draft.display_name = nameInput.value;
  });

  const identity = document.createElement("div");
  identity.className = "identity";
  identity.textContent =
    `${state.current.platform} · ${state.current.user_id}` +
    ` · 更新于 ${state.draft.updated_at || "未知"}`;

  head.append(nameInput, identity);
  return head;
}

function renderStatus() {
  const section = document.createElement("section");
  section.className = "field-section";

  const head = document.createElement("div");
  head.className = "field-head";
  const label = document.createElement("span");
  label.className = "field-label";
  label.textContent = "当前状态";
  const hint = document.createElement("span");
  hint.className = "setting-desc";
  hint.textContent = "阶段性总状态（如备考、放假、出差），不要填一次性琐事";
  head.append(label, hint);

  const area = document.createElement("textarea");
  area.className = "status-area";
  area.placeholder = "例如：备考中，压力有点大";
  area.value = state.draft.status;
  area.addEventListener("input", () => {
    state.draft.status = area.value;
  });

  section.append(head, area);
  return section;
}

function renderFieldSection(field) {
  const section = document.createElement("section");
  section.className = "field-section";

  const head = document.createElement("div");
  head.className = "field-head";
  const label = document.createElement("span");
  label.className = "field-label";
  label.textContent = `${field.label}（${state.draft[field.key].length}）`;

  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.className = "icon-btn";
  addBtn.textContent = "＋ 添加";
  addBtn.addEventListener("click", () => {
    state.draft[field.key].push("");
    renderEditor();
    const rows = document.querySelectorAll(`[data-field="${field.key}"] .field-row input`);
    const last = rows[rows.length - 1];
    if (last) last.focus();
  });

  head.append(label, addBtn);

  const rows = document.createElement("div");
  rows.className = "field-rows";
  rows.dataset.field = field.key;

  state.draft[field.key].forEach((entry, index) => {
    const row = document.createElement("div");
    row.className = "field-row";

    const input = document.createElement("input");
    input.className = "input";
    input.placeholder = field.placeholder;
    input.value = entry;
    input.addEventListener("input", () => {
      state.draft[field.key][index] = input.value;
    });

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "icon-btn";
    removeBtn.textContent = "✕";
    removeBtn.title = "删除这条";
    removeBtn.addEventListener("click", () => {
      state.draft[field.key].splice(index, 1);
      renderEditor();
    });

    row.append(input, removeBtn);
    rows.appendChild(row);
  });

  section.append(head, rows);
  return section;
}

function renderFoot() {
  const foot = document.createElement("div");
  foot.className = "editor-foot";

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "btn danger";
  deleteBtn.textContent = "删除档案";
  deleteBtn.addEventListener("click", () => {
    deleteProfile(deleteBtn).catch(handleError);
  });

  const right = document.createElement("div");
  right.className = "foot-right";

  const updateBtn = document.createElement("button");
  updateBtn.type = "button";
  updateBtn.className = "btn ghost";
  updateBtn.textContent = "触发总结更新";
  updateBtn.title = "根据最近缓存的对话，让模型总结后更新这份档案";
  updateBtn.addEventListener("click", () => {
    triggerUpdate(updateBtn).catch(handleError);
  });

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "btn primary";
  saveBtn.textContent = "保存";
  saveBtn.addEventListener("click", () => {
    saveProfile(saveBtn).catch(handleError);
  });

  right.append(updateBtn, saveBtn);
  foot.append(deleteBtn, right);
  return foot;
}

async function saveProfile(button) {
  buttonBusy(button, true);
  try {
    const result = await apiPost("profile/save", {
      platform: state.current.platform,
      user_id: state.current.user_id,
      display_name: state.draft.display_name,
      profile: buildPayload(),
    });
    state.draft = normalizeDraft(result.profile);
    renderEditor();
    await loadProfiles();
    showToast("档案已保存", "success");
  } finally {
    buttonBusy(button, false);
  }
}

async function triggerUpdate(button) {
  buttonBusy(button, true);
  try {
    const result = await apiPost("profile/update", {
      platform: state.current.platform,
      user_id: state.current.user_id,
    });
    state.draft = normalizeDraft(result.profile);
    renderEditor();
    await loadProfiles();
    showToast(result.updated ? "档案已根据最近对话更新" : "没有发现新的可记录信息", "success");
  } finally {
    buttonBusy(button, false);
  }
}

async function deleteProfile(button) {
  if (!window.confirm("确定删除该用户的档案吗？此操作不可恢复。")) return;
  buttonBusy(button, true);
  try {
    await apiPost("profile/delete", {
      platform: state.current.platform,
      user_id: state.current.user_id,
    });
    state.current = null;
    state.draft = null;
    renderEditor();
    await loadProfiles();
    showToast("档案已删除", "success");
  } finally {
    buttonBusy(button, false);
  }
}

// ------------------------------------------------------------------ 插件设置

function settingRow(name, label, description, control) {
  const row = document.createElement("div");
  row.className = "setting-row";

  const info = document.createElement("div");
  info.className = "setting-info";
  const nameEl = document.createElement("div");
  nameEl.className = "setting-name";
  nameEl.textContent = label;
  const descEl = document.createElement("div");
  descEl.className = "setting-desc";
  descEl.textContent = description;
  info.append(nameEl, descEl);

  const controlWrap = document.createElement("div");
  controlWrap.className = "setting-control";
  controlWrap.appendChild(control);
  // 标记放在真正的表单控件上，便于统一收集取值
  const target = control.matches("input, select, textarea")
    ? control
    : control.querySelector("input, select, textarea") || control;
  target.dataset.setting = name;

  row.append(info, controlWrap);
  return row;
}

function switchControl(value) {
  const label = document.createElement("label");
  label.className = "switch";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = Boolean(value);
  const track = document.createElement("span");
  track.className = "switch-track";
  label.append(input, track);
  return label;
}

function numberControl(value) {
  const input = document.createElement("input");
  input.className = "input";
  input.type = "number";
  input.value = String(value ?? "");
  return input;
}

function textControl(value) {
  const input = document.createElement("input");
  input.className = "input";
  input.type = "text";
  input.value = String(value ?? "");
  input.placeholder = "留空则跟随会话模型";
  return input;
}

function providerControl(current, providers) {
  const select = document.createElement("select");
  select.className = "input";
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = "跟随会话模型";
  select.appendChild(empty);
  let matched = false;
  for (const provider of providers) {
    const option = document.createElement("option");
    option.value = provider.id;
    option.textContent = provider.name;
    if (provider.id === current) matched = true;
    select.appendChild(option);
  }
  if (current && !matched) {
    const option = document.createElement("option");
    option.value = current;
    option.textContent = current;
    select.appendChild(option);
  }
  select.value = current || "";
  return select;
}

async function openSettings() {
  const data = await apiGet("settings");
  state.settings = data;
  renderSettings(data);
  $("settings-modal").classList.remove("hidden");
}

function renderSettings(data) {
  const body = $("settings-body");
  body.textContent = "";
  const config = data.config || {};
  const limits = data.limits || {};
  const providers = Array.isArray(data.providers) ? data.providers : [];
  const range = (name) => {
    const limit = limits[name];
    return limit ? `（范围 ${limit.min} - ${limit.max}）` : "";
  };

  body.appendChild(
    settingRow("enabled", "启用插件", "关闭后不再统计、更新和注入任何档案", switchControl(config.enabled)),
  );
  body.appendChild(
    settingRow(
      "remind_after_messages",
      "档案维护提醒阈值",
      `用户累计发送多少条消息后，提醒 AI 判断是否需要更新档案${range("remind_after_messages")}`,
      numberControl(config.remind_after_messages),
    ),
  );
  body.appendChild(
    settingRow(
      "tool_enabled",
      "启用档案更新工具",
      "允许 AI 在对话中自主调用工具记录信息；关闭后仅保留手动指令",
      switchControl(config.tool_enabled),
    ),
  );
  body.appendChild(
    settingRow(
      "inject_enabled",
      "对话时注入档案",
      "让 AI 在对话中了解当前用户",
      switchControl(config.inject_enabled),
    ),
  );
  body.appendChild(
    settingRow(
      "inject_max_chars",
      "注入档案最大字符数",
      `注入内容超长时会被截断${range("inject_max_chars")}`,
      numberControl(config.inject_max_chars),
    ),
  );
  body.appendChild(
    settingRow(
      "context_size",
      "总结回顾消息条数",
      `手动触发总结时回顾的对话条数${range("context_size")}`,
      numberControl(config.context_size),
    ),
  );
  body.appendChild(
    settingRow(
      "summary_provider_id",
      "档案总结使用的模型",
      providers.length > 0
        ? "留空则使用用户会话正在使用的模型"
        : "未能获取模型列表，可直接填写模型 ID；留空则跟随会话模型",
      providers.length > 0
        ? providerControl(config.summary_provider_id, providers)
        : textControl(config.summary_provider_id),
    ),
  );
  body.appendChild(
    settingRow(
      "allow_admin_view",
      "允许管理员查看/清除他人档案",
      "关闭后 /profile admin 指令将被禁用",
      switchControl(config.allow_admin_view),
    ),
  );
}

function collectSettings() {
  const config = {};
  const body = $("settings-body");
  for (const element of body.querySelectorAll("[data-setting]")) {
    const name = element.dataset.setting;
    if (element.type === "checkbox") {
      config[name] = element.checked;
    } else if (element.type === "number") {
      const parsed = Number.parseInt(element.value, 10);
      config[name] = Number.isNaN(parsed) ? 0 : parsed;
    } else {
      config[name] = element.value;
    }
  }
  return config;
}

async function saveSettings(button) {
  buttonBusy(button, true);
  try {
    const result = await apiPost("settings/save", { config: collectSettings() });
    if (result && result.config) {
      state.settings = { ...(state.settings || {}), config: result.config };
    }
    showToast("设置已保存并即时生效", "success");
    $("settings-modal").classList.add("hidden");
  } finally {
    buttonBusy(button, false);
  }
}

// ------------------------------------------------------------------ 初始化

function bindEvents() {
  $("btn-refresh").addEventListener("click", (event) => {
    const button = event.currentTarget;
    buttonBusy(button, true);
    loadProfiles()
      .then(() => showToast("已刷新", "success"))
      .catch(handleError)
      .finally(() => buttonBusy(button, false));
  });

  $("btn-settings").addEventListener("click", () => {
    openSettings().catch(handleError);
  });

  $("btn-settings-close").addEventListener("click", () => {
    $("settings-modal").classList.add("hidden");
  });

  $("settings-modal").addEventListener("click", (event) => {
    if (event.target.dataset.close === "1") {
      $("settings-modal").classList.add("hidden");
    }
  });

  $("btn-settings-save").addEventListener("click", (event) => {
    saveSettings(event.currentTarget).catch(handleError);
  });

  $("search").addEventListener("input", (event) => {
    state.keyword = event.target.value;
    renderList();
  });
}

async function init() {
  if (!bridge) {
    $("editor").textContent = "";
    const placeholder = document.createElement("div");
    placeholder.className = "placeholder";
    placeholder.textContent = "未检测到 AstrBot 页面桥接（请通过插件详情页打开本页面）。";
    $("editor").appendChild(placeholder);
    return;
  }

  try {
    await bridge.ready();
  } catch (error) {
    console.warn("bridge.ready() failed", error);
  }

  bindEvents();

  const themeHandler = () => {
    const context = bridge.getContext ? bridge.getContext() : null;
    if (context && typeof context.isDark === "boolean") {
      document.documentElement.dataset.theme = context.isDark ? "dark" : "light";
    }
  };
  themeHandler();
  if (typeof bridge.onContext === "function") {
    bridge.onContext(themeHandler);
  }

  try {
    await loadProfiles();
  } catch (error) {
    handleError(error);
  }
}

init();
