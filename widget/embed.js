/**
 * ccf-chatbot-widget.js — Embeddable chat widget for Cornwall Community Foundation
 *
 * How to use:
 *   1. Add this to your site's <head> or just before </body>:
 *      <script src="https://your-server.com/widget/embed.js"></script>
 *
 *   2. Or paste the entire code inline and call:
 *      CCFChatbot.init({ apiBase: "https://your-server.com" })
 *
 * Configuration:
 *   - apiBase: URL of the running server.py (default: window.location.origin)
 *   - position: "bottom-right" | "bottom-left" (default: "bottom-right")
 *   - primaryColor: hex colour for the header/button (default: "#1E3A5F")
 *   - title: widget header text (default: "Ask CCF")
 *   - greeting: initial bot message (default: "Hi! How can I help you with CCF grants?")
 */

(function () {
  "use strict";

  // ---- Defaults ----------------------------------------------------------
  var DEFAULTS = {
    apiBase: window.location.origin,
    position: "bottom-right",
    primaryColor: "#1E3A5F",
    title: "Ask CCF",
    greeting:
      "Hi! I can answer questions about grants, eligibility, and applications at Cornwall Community Foundation. How can I help?",
    placeholder: "Type your question...",
    disclaimer:
      "Answers are generated from the CCF website content and may be incomplete. Always confirm critical information with the CCF team.",
  };

  // ---- State -------------------------------------------------------------
  var state = {
    open: false,
    messages: [],
    waiting: false,
  };

  // ---- DOM helpers -------------------------------------------------------
  function createEl(tag, attrs, children) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "style") {
          Object.assign(el.style, attrs[k]);
        } else if (k === "className") {
          el.className = attrs[k];
        } else {
          el.setAttribute(k, attrs[k]);
        }
      });
    }
    if (children) {
      (Array.isArray(children) ? children : [children]).forEach(function (c) {
        if (typeof c === "string") {
          el.appendChild(document.createTextNode(c));
        } else if (c instanceof Node) {
          el.appendChild(c);
        }
      });
    }
    return el;
  }

  function $(sel, ctx) {
    return (ctx || document).querySelector(sel);
  }

  function $$(sel, ctx) {
    return Array.from((ctx || document).querySelectorAll(sel));
  }

  // ---- Styles ------------------------------------------------------------
  var STYLES = {
    container: {
      position: "fixed",
      zIndex: "999999",
      fontFamily:
        '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
      fontSize: "14px",
      lineHeight: "1.5",
      color: "#333",
    },
    button: {
      width: "56px",
      height: "56px",
      borderRadius: "50%",
      border: "none",
      cursor: "pointer",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
      transition: "transform 0.2s ease",
    },
    chatbox: {
      width: "360px",
      maxWidth: "calc(100vw - 24px)",
      height: "520px",
      maxHeight: "calc(100vh - 120px)",
      borderRadius: "12px",
      overflow: "hidden",
      display: "flex",
      flexDirection: "column",
      boxShadow: "0 8px 32px rgba(0,0,0,0.18)",
      border: "1px solid rgba(0,0,0,0.08)",
      backgroundColor: "#fff",
      position: "absolute",
      bottom: "72px",
      right: "0",
      opacity: "0",
      transform: "translateY(16px) scale(0.96)",
      pointerEvents: "none",
      transition: "opacity 0.25s ease, transform 0.25s ease",
    },
    chatboxVisible: {
      opacity: "1",
      transform: "translateY(0) scale(1)",
      pointerEvents: "auto",
    },
    header: {
      padding: "14px 16px",
      color: "#fff",
      fontWeight: "600",
      fontSize: "15px",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      flexShrink: "0",
    },
    closeBtn: {
      background: "none",
      border: "none",
      color: "#fff",
      cursor: "pointer",
      fontSize: "20px",
      padding: "0 4px",
      opacity: "0.8",
    },
    messages: {
      flex: "1",
      overflowY: "auto",
      padding: "12px 14px",
      display: "flex",
      flexDirection: "column",
      gap: "8px",
      scrollBehavior: "smooth",
    },
    bubble: {
      maxWidth: "85%",
      padding: "10px 14px",
      borderRadius: "16px",
      fontSize: "14px",
      lineHeight: "1.5",
      wordWrap: "break-word",
      whiteSpace: "pre-wrap",
    },
    userBubble: {
      alignSelf: "flex-end",
      backgroundColor: "#1E3A5F",
      color: "#fff",
      borderBottomRightRadius: "4px",
    },
    botBubble: {
      alignSelf: "flex-start",
      backgroundColor: "#f0f2f5",
      color: "#333",
      borderBottomLeftRadius: "4px",
    },
    sourceLink: {
      color: "#1E3A5F",
      textDecoration: "underline",
      fontSize: "12px",
      display: "inline-block",
      marginTop: "4px",
    },
    disclaimer: {
      fontSize: "11px",
      color: "#888",
      textAlign: "center",
      padding: "8px 14px",
      borderTop: "1px solid #eee",
      flexShrink: "0",
    },
    inputBar: {
      display: "flex",
      padding: "10px 12px",
      borderTop: "1px solid #eee",
      flexShrink: "0",
      gap: "8px",
    },
    input: {
      flex: "1",
      border: "1px solid #ddd",
      borderRadius: "20px",
      padding: "8px 14px",
      fontSize: "14px",
      outline: "none",
    },
    sendBtn: {
      width: "38px",
      height: "38px",
      borderRadius: "50%",
      border: "none",
      color: "#fff",
      cursor: "pointer",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      flexShrink: "0",
    },
    typing: {
      alignSelf: "flex-start",
      backgroundColor: "#f0f2f5",
      padding: "10px 16px",
      borderRadius: "16px",
      borderBottomLeftRadius: "4px",
      fontSize: "14px",
      color: "#888",
    },
    sourceTag: {
      fontSize: "11px",
      color: "#666",
      marginTop: "6px",
      borderTop: "1px solid #e0e0e0",
      paddingTop: "4px",
    },
  };

  // ---- Widget builder ----------------------------------------------------
  var config = {};
  var container, chatbox, messagesEl, inputEl, sendBtn, button;

  function buildWidget() {
    // Position styles
    var posStyle = {};
    if (config.position === "bottom-left") {
      posStyle = { bottom: "20px", left: "20px" };
    } else {
      posStyle = { bottom: "20px", right: "20px" };
    }

    container = createEl("div", { style: Object.assign({}, STYLES.container, posStyle) });

    // --- Chatbox ---
    chatbox = createEl("div", {
      style: Object.assign({}, STYLES.chatbox, { right: "0" }),
      id: "ccf-chatbox",
    });

    // Header
    var header = createEl("div", {
      style: Object.assign({}, STYLES.header, { backgroundColor: config.primaryColor }),
    }, [
      config.title,
      createEl("button", {
        style: STYLES.closeBtn,
        id: "ccf-close-btn",
        "aria-label": "Close chat",
      }, ["✕"]),
    ]);
    chatbox.appendChild(header);

    // Messages
    messagesEl = createEl("div", { style: STYLES.messages, id: "ccf-messages" });
    chatbox.appendChild(messagesEl);

    // Disclaimer
    chatbox.appendChild(
      createEl("div", { style: STYLES.disclaimer }, [config.disclaimer])
    );

    // Input bar
    var inputBar = createEl("div", { style: STYLES.inputBar });
    inputEl = createEl("input", {
      style: STYLES.input,
      type: "text",
      placeholder: config.placeholder,
      id: "ccf-input",
    });
    sendBtn = createEl("button", {
      style: Object.assign({}, STYLES.sendBtn, { backgroundColor: config.primaryColor }),
      id: "ccf-send-btn",
      "aria-label": "Send message",
    }, ["➤"]);
    inputBar.appendChild(inputEl);
    inputBar.appendChild(sendBtn);
    chatbox.appendChild(inputBar);

    // --- Toggle button ---
    button = createEl("button", {
      style: Object.assign({}, STYLES.button, { backgroundColor: config.primaryColor }),
      id: "ccf-button",
      "aria-label": "Open chat",
    }, ["💬"]);

    container.appendChild(chatbox);
    container.appendChild(button);
    document.body.appendChild(container);

    // ---- Event listeners ----
    button.addEventListener("click", toggleChat);
    $("#ccf-close-btn").addEventListener("click", toggleChat);
    sendBtn.addEventListener("click", sendMessage);
    inputEl.addEventListener("keydown", function (e) {
      if (e.key === "Enter") sendMessage();
    });

    // Add greeting
    addBotMessage(config.greeting);
  }

  // ---- Toggle ------------------------------------------------------------
  function toggleChat() {
    state.open = !state.open;
    if (state.open) {
      chatbox.style.opacity = "1";
      chatbox.style.transform = "translateY(0) scale(1)";
      chatbox.style.pointerEvents = "auto";
      button.style.display = "none";
      inputEl.focus();
    } else {
      chatbox.style.opacity = "0";
      chatbox.style.transform = "translateY(16px) scale(0.96)";
      chatbox.style.pointerEvents = "none";
      button.style.display = "flex";
    }
  }

  // ---- Messages ----------------------------------------------------------
  function addUserMessage(text) {
    var bubble = createEl("div", {
      style: Object.assign({}, STYLES.bubble, STYLES.userBubble),
    }, [text]);
    messagesEl.appendChild(bubble);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function addBotMessage(text, sources) {
    var bubble = createEl("div", {
      style: Object.assign({}, STYLES.bubble, STYLES.botBubble),
    });

    // Answer text
    var textEl = createEl("div", {}, [text]);
    bubble.appendChild(textEl);

    // Sources
    if (sources && sources.length > 0) {
      var sourceDiv = createEl("div", { style: STYLES.sourceTag });

      sources.forEach(function (s, i) {
        var link = createEl("a", {
          style: STYLES.sourceLink,
          href: s.url,
          target: "_blank",
          rel: "noopener noreferrer",
        }, ["📄 " + s.title]);
        sourceDiv.appendChild(link);
        if (i < sources.length - 1) {
          sourceDiv.appendChild(document.createTextNode(" · "));
        }
      });

      bubble.appendChild(sourceDiv);
    }

    messagesEl.appendChild(bubble);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function addTypingIndicator() {
    var el = createEl("div", { style: STYLES.typing, id: "ccf-typing" }, ["Thinking..."]);
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function removeTypingIndicator() {
    var el = $("#ccf-typing");
    if (el) el.remove();
  }

  // ---- Chat API ----------------------------------------------------------
  function sendMessage() {
    var text = inputEl.value.trim();
    if (!text || state.waiting) return;

    inputEl.value = "";
    addUserMessage(text);
    state.waiting = true;
    addTypingIndicator();

    var xhr = new XMLHttpRequest();
    xhr.open("POST", config.apiBase + "/chat", true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onload = function () {
      removeTypingIndicator();
      state.waiting = false;
      if (xhr.status === 200) {
        var data = JSON.parse(xhr.responseText);
        addBotMessage(data.answer, data.sources);
      } else {
        addBotMessage(
          "Sorry, I couldn't process your request. Please try again or contact the CCF team directly."
        );
      }
    };
    xhr.onerror = function () {
      removeTypingIndicator();
      state.waiting = false;
      addBotMessage(
        "A network error occurred. Please check your connection and try again."
      );
    };
    xhr.send(JSON.stringify({ message: text }));
  }

  // ---- Init --------------------------------------------------------------
  var CCFChatbot = {
    init: function (opts) {
      opts = opts || {};
      config = {};
      Object.keys(DEFAULTS).forEach(function (k) {
        config[k] = opts.hasOwnProperty(k) ? opts[k] : DEFAULTS[k];
      });
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", buildWidget);
      } else {
        buildWidget();
      }
    },
  };

  // Auto-init if the script is loaded directly
  window.CCFChatbot = CCFChatbot;

  // If the script tag has a data-api-base attribute, auto-init
  var scriptTag = document.currentScript;
  if (scriptTag && scriptTag.getAttribute("data-api-base")) {
    CCFChatbot.init({
      apiBase: scriptTag.getAttribute("data-api-base"),
      primaryColor: scriptTag.getAttribute("data-primary-color") || undefined,
      position: scriptTag.getAttribute("data-position") || undefined,
      title: scriptTag.getAttribute("data-title") || undefined,
    });
  }
})();