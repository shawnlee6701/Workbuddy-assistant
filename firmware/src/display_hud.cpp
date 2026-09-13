#include "display_hud.h"
#include "native_lcd_probe.h"

// 参考实物界面与 Web 端 1:1 精确色彩体系 (RGB565)
#define COLOR_BG            0x0000  // #000000 纯黑底
#define COLOR_SURFACE       0x0861  // #12151A 暗灰底
#define COLOR_BORDER        0x2965  // #2B3543 分割线/边框灰
#define COLOR_TEXT_WHITE    0xFFFF  // #FFFFFF 主白字
#define COLOR_TEXT_MUTED    0xBDF7  // #B0BAC9 次级说明字
#define COLOR_TEXT_DIM      0x7BEF  // #7B889B 标签暗文字

// 状态色系 (与 Web 端 100% 精确对齐)
#define COLOR_STATE_RUNNING     0x07FA  // #00F2FE 亮青蓝 (执行中)
#define COLOR_STATE_COMPLETED   0x47F0  // #00E676 亮绿色 (已完成)
#define COLOR_STATE_APPROVAL    0xFDC0  // #F59E0B 警示橙 (等待确认)
#define COLOR_STATE_ANSWER      0x8AEF  // #8B5CF6 交互紫 (等待回答)
#define COLOR_STATE_ERROR       0xF206  // #EF4444 错误红 (异常中断)
#define COLOR_STATE_IDLE        0x7BEF  // #7B889B 待命灰 (待命中)

static inline uint16_t getStateColor(AgentState state) {
    switch (state) {
        case STATE_RUNNING:       return COLOR_STATE_RUNNING;
        case STATE_COMPLETED:     return COLOR_STATE_COMPLETED;
        case STATE_NEED_APPROVAL: return COLOR_STATE_APPROVAL;
        case STATE_NEED_ANSWER:   return COLOR_STATE_ANSWER;
        case STATE_ERROR:         return COLOR_STATE_ERROR;
        case STATE_IDLE:
        default:                  return COLOR_STATE_IDLE;
    }
}

DisplayHud::DisplayHud() : _canvas(&_tft) {}

bool DisplayHud::init() {
    // LovyanGFX 只负责离屏绘制；物理屏幕由已验证的 esp_lcd 驱动输出。
    _canvas.setColorDepth(16);
    _canvas.setPsram(true);
    if (!_canvas.createSprite(320, 240)) {
        Serial.println("[HUD] ERROR: sprite allocation failed");
        return false;
    }
    _canvas.setFont(&fonts::efontCN_12);
    
    showBootScreen();
    return true;
}

void DisplayHud::showBootScreen() {
    _canvas.fillScreen(COLOR_BG);
    _canvas.drawRect(0, 0, 320, 240, COLOR_BORDER);
    
    _canvas.setTextSize(1);
    _canvas.setTextColor(0x345F, COLOR_BG);
    _canvas.drawString("WORKBUDDY · 桌面状态屏", 20, 40);
    
    _canvas.setTextColor(COLOR_TEXT_WHITE, COLOR_BG);
    _canvas.drawString("立创实战派 ESP32-S3", 20, 65);
    
    _canvas.setTextColor(COLOR_TEXT_MUTED, COLOR_BG);
    _canvas.drawString("正在等待 Workbuddy 连接...", 20, 100);
    _canvas.drawString("串口速率：115200", 20, 120);
    
    // 底部状态提示
    _canvas.fillRoundRect(20, 190, 280, 28, 4, COLOR_SURFACE);
    _canvas.drawRoundRect(20, 190, 280, 28, 4, COLOR_BORDER);
    _canvas.setTextColor(0x9E38, COLOR_SURFACE);
    _canvas.drawString("系统已就绪 · 连接即用", 72, 198);
    
    nativeLcdDraw(_canvas.getBuffer());
}

void DisplayHud::testPanel() {
    _canvas.fillScreen(TFT_WHITE);
    _canvas.setTextColor(TFT_BLACK, TFT_WHITE);
    _canvas.setTextSize(2);
    _canvas.drawString("WORKBUDDY 屏幕测试", 10, 80);
    nativeLcdDraw(_canvas.getBuffer());
}

void DisplayHud::drawHeader(const HudData& data) {
    _canvas.setTextSize(1);
    _canvas.setTextColor(COLOR_TEXT_WHITE, COLOR_BG);
    _canvas.drawString("workbuddy", 12, 10);

    // 当前模型只在 Bridge 取得真实字段时展示；避免空占位。
    if (!data.modelName.isEmpty()) {
        String model = data.modelName;
        while (_canvas.textWidth(model + "...") > 150 && model.length() > 3) {
            int index = model.length() - 1;
            while (index > 0 && ((uint8_t)model[index] & 0xC0) == 0x80) index--;
            model.remove(index);
        }
        if (model != data.modelName) model += "...";
        _canvas.setTextColor(COLOR_STATE_RUNNING, COLOR_BG);
        _canvas.drawString("· " + model, 79, 10);
    }

    _canvas.setTextColor(COLOR_TEXT_WHITE, COLOR_BG);
    _canvas.drawString(data.timeStr, 250, 10);
    
    // 状态指示圆点随当前状态动态变色
    _canvas.fillCircle(308, 16, 4, getStateColor(data.state));
}

void DisplayHud::drawAlertCard(const HudData& data) {
    uint16_t stateColor = getStateColor(data.state);

    // 左侧强调色条
    _canvas.fillRoundRect(12, 40, 5, 42, 2, stateColor);
    
    // 状态大标题
    _canvas.setTextSize(2);
    _canvas.setTextColor(COLOR_TEXT_WHITE, COLOR_BG);
    _canvas.drawString(data.stateText, 28, 42);

    // 状态辅助描述
    _canvas.setTextSize(1);
    _canvas.setTextColor(COLOR_TEXT_MUTED, COLOR_BG);
    _canvas.drawString(data.alertDesc, 12, 94);

    if (data.state == STATE_NEED_APPROVAL) {
        _canvas.setTextColor(stateColor, COLOR_BG);
        _canvas.drawString("按 BOOT 键确认", 210, 94);
    }
}

void DisplayHud::drawMetricsGrid(const HudData& data) {
    uint16_t stateColor = getStateColor(data.state);
    
    _canvas.drawFastHLine(12, 124, 296, COLOR_BORDER);
    
    // 指标栏左侧 Label 颜色与当前状态 100% 对应
    _canvas.setTextSize(1);
    _canvas.setTextColor(stateColor, COLOR_BG);
    _canvas.drawString(data.stateText, 12, 136);

    _canvas.setTextColor(COLOR_TEXT_WHITE, COLOR_BG);
    _canvas.drawString("用时 " + data.durationStr, 96, 136);

    _canvas.setTextColor(COLOR_STATE_RUNNING, COLOR_BG);
    _canvas.drawString("同步 " + data.stepStr, 232, 136);
    _canvas.drawFastHLine(12, 157, 296, COLOR_BORDER);
}

void DisplayHud::drawTimeline(const HudData& data) {
    _canvas.setTextSize(1);
    _canvas.setTextColor(COLOR_TEXT_DIM, COLOR_BG);
    _canvas.drawString("当前任务", 12, 170);

    _canvas.setTextColor(COLOR_TEXT_WHITE, COLOR_BG);
    String title = data.alertTitle;
    while (_canvas.textWidth(title + "...") > 296 && title.length() > 3) {
        int index = title.length() - 1;
        while (index > 0 && ((uint8_t)title[index] & 0xC0) == 0x80) index--;
        title.remove(index);
    }
    if (title != data.alertTitle) title += "...";
    _canvas.drawString(title, 12, 191);

    _canvas.drawFastHLine(12, 214, 296, COLOR_BORDER);
    _canvas.setTextColor(COLOR_TEXT_DIM, COLOR_BG);
    if (!data.timeline.empty()) {
        _canvas.drawString("最新进度  " + data.timeline[0].duration, 12, 222);
    } else {
        _canvas.drawString("等待新的任务", 12, 222);
    }
}

void DisplayHud::update(const HudData& data) {
    _canvas.fillScreen(COLOR_BG);
    drawHeader(data);
    drawAlertCard(data);
    drawMetricsGrid(data);
    drawTimeline(data);
    
    // 推送到物理屏幕（零撕裂双缓冲）
    nativeLcdDraw(_canvas.getBuffer());
}
