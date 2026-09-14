#include <Arduino.h>
#include <ArduinoJson.h>
#include "bsp_board.h"
#include "display_hud.h"
#include "native_lcd_probe.h"
#include "wifi_v2.h"

DisplayHud hud;
HudData currentData;
String serialBuffer = "";
bool lastKeyState = false;
unsigned long lastKeyDebounce = 0;
bool displayReady = false;
WifiV2Manager wifiManager;
unsigned long keyPressedAt = 0;
bool resetTriggered = false;

void applyHudPayload(JsonObjectConst doc) {
    String stateStr = doc["state"] | "IDLE";
    if (stateStr == "RUNNING") {
        currentData.state = STATE_RUNNING;
        currentData.stateText = "执行中";
    } else if (stateStr == "NEED_ANSWER") {
        currentData.state = STATE_NEED_ANSWER;
        currentData.stateText = "等待回答";
    } else if (stateStr == "NEED_APPROVAL") {
        currentData.state = STATE_NEED_APPROVAL;
        currentData.stateText = "等待确认";
    } else if (stateStr == "COMPLETED") {
        currentData.state = STATE_COMPLETED;
        currentData.stateText = "已完成";
    } else if (stateStr == "ERROR") {
        currentData.state = STATE_ERROR;
        currentData.stateText = "异常中断";
    } else {
        currentData.state = STATE_IDLE;
        currentData.stateText = "待命中";
    }

    currentData.threadName    = doc["thread"] | "Workbuddy 实时状态";
    currentData.timeStr       = doc["time"] | "00:00:00";
    currentData.alertTitle    = doc["alert_title"] | "";
    currentData.alertDesc     = doc["alert_desc"] | "";
    currentData.stepStr       = doc["step"] | "0/0";
    currentData.toolsStr      = doc["tools"] | "0 次";
    currentData.durationStr   = doc["duration"] | "00:00";
    currentData.tokenStr      = doc["tokens"] | (doc["session_tokens"] | "0k");
    currentData.todayTokenStr = doc["today_tokens"] | "";
    currentData.modelName     = doc["model"] | "";
    currentData.networkStatus = wifiManager.stateText();
    currentData.networkIp     = wifiManager.ipText();
    currentData.networkRssi   = wifiManager.rssi();

    currentData.timeline.clear();
    JsonArrayConst tl = doc["timeline"].as<JsonArrayConst>();
    for (JsonObjectConst obj : tl) {
        TimelineItem item;
        item.text     = obj["text"].as<String>();
        item.duration = obj["dur"].as<String>();
        item.done     = obj["done"] | false;
        item.active   = obj["active"] | false;
        currentData.timeline.push_back(item);
    }

    if (!displayReady) {
        nativeLcdProbe();
        displayReady = hud.init();
    }
    if (displayReady) {
        hud.update(currentData);
        Serial.printf("[HUD] OK -> %s | %s | model=%s | token=%s | %s\n",
                      currentData.timeStr.c_str(), stateStr.c_str(),
                      currentData.modelName.isEmpty() ? "-" : currentData.modelName.c_str(),
                      currentData.tokenStr.c_str(), currentData.alertTitle.c_str());
    }
}

void printDiagnostics() {
    Serial.printf("[DIAG] ready=%d psram=%u heap=%u BL_GPIO42=%d\n",
                  displayReady, ESP.getPsramSize(), ESP.getFreeHeap(), digitalRead(PIN_LCD_BL));
    for (uint8_t reg = 0; reg < 4; ++reg) {
        Wire.beginTransmission(BSPBoard::pca9557Addr);
        Wire.write(reg);
        int err = Wire.endTransmission(false);
        int count = Wire.requestFrom(BSPBoard::pca9557Addr, (uint8_t)1);
        int value = count ? Wire.read() : -1;
        Serial.printf("[DIAG] expander=0x%02X reg=%u value=0x%02X error=%d\n",
                      BSPBoard::pca9557Addr, reg, value, err);
    }
}

void parseIncomingJson(const String& jsonStr) {
    if (jsonStr == "LCD_TEST") { hud.testPanel(); Serial.println("[DIAG] Direct white screen test sent"); return; }
    if (jsonStr == "DIAG") { printDiagnostics(); return; }
    if (jsonStr == "BL_ON") { BSPBoard::setBacklight(true); printDiagnostics(); return; }
    if (jsonStr == "BL_OFF") { BSPBoard::setBacklight(false); printDiagnostics(); return; }

    // 使用更大的缓冲区以确保长文本和中文不截断
    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, jsonStr);
    if (error) {
        Serial.printf("[HUD] JSON parse error: %s (input len=%d)\n", error.c_str(), jsonStr.length());
        return;
    }

    JsonObjectConst root = doc.as<JsonObjectConst>();
    if (wifiManager.handleUsbCommand(root)) return;
    if (wifiManager.handleSerialSnapshot(root)) return;
    applyHudPayload(root);  // V1.1 legacy USB payload remains supported.
}

void setup() {
    Serial.begin(115200);
    delay(300);
    Serial.println("\n=== Workbuddy Desktop HUD Starting ===");

    // 1. 初始化开发板基础外设与背光
    bool boardReady = BSPBoard::init();
    Serial.printf("[BSP] ready=%d PSRAM=%u bytes\n", boardReady, ESP.getPsramSize());
    
    // 2. 初始化显示屏幕与双缓冲
    bool panelReady = boardReady && nativeLcdProbe();
    displayReady = panelReady && hud.init();
    Serial.printf("[HUD] displayReady=%d (native panel + HUD canvas)\n", displayReady);

    // 3. V2.0 Wi-Fi transport; missing credentials keeps the USB path active.
    wifiManager.begin(applyHudPayload);
}

void loop() {
    // 1. 串口命令读取 (高容错行缓冲区)
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            serialBuffer.trim();
            if (serialBuffer.length() > 0) {
                parseIncomingJson(serialBuffer);
                serialBuffer = "";
            }
        } else {
            if (serialBuffer.length() >= 4096) {
                serialBuffer = ""; // 防止异常堆积溢出
            }
            serialBuffer += c;
        }
    }

    // 2. V2.0 network state machine.
    wifiManager.loop();

    // 3. BOOT: short approve, 1.5–10s hint, hold through 3s reset countdown.
    bool isPressed = BSPBoard::isKeyPressed();
    if (isPressed != lastKeyState && (millis() - lastKeyDebounce > 50)) {
        lastKeyDebounce = millis();
        lastKeyState = isPressed;
        if (isPressed) {
            keyPressedAt = millis();
            resetTriggered = false;
        } else {
            unsigned long held = millis() - keyPressedAt;
            if (held < 1500 && currentData.state == STATE_NEED_APPROVAL) {
                wifiManager.sendKeyPress();
            }
            if (!resetTriggered && displayReady) hud.update(currentData);
        }
    }

    if (isPressed && !resetTriggered) {
        unsigned long held = millis() - keyPressedAt;
        if (held >= 13000) {
            wifiManager.clearConfiguration();
            resetTriggered = true;
            if (displayReady) hud.showSystemMessage("网络配置已清除", "请连接 USB 重新配置 Wi-Fi", TFT_RED);
        } else if (held >= 10000) {
            int remaining = 3 - static_cast<int>((held - 10000) / 1000);
            if (displayReady) hud.showSystemMessage("继续按住以重置", String(remaining) + " 秒后清除 Wi-Fi 与配对", TFT_RED);
        } else if (held >= 1500) {
            if (displayReady) hud.showSystemMessage("连接 USB 配置", "请在电脑 Dashboard 设置 Wi-Fi", TFT_CYAN);
        }
    }

    delay(5);
}
