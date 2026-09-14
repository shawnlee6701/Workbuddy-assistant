#pragma once
#include <Arduino.h>
#include "bsp_board.h"
#include <vector>

enum AgentState {
    STATE_IDLE = 0,
    STATE_RUNNING,
    STATE_NEED_ANSWER,
    STATE_NEED_APPROVAL,
    STATE_COMPLETED,
    STATE_ERROR
};

struct TimelineItem {
    String text;
    String duration;
    bool done;
    bool active;
};

struct HudData {
    AgentState state = STATE_IDLE;
    String stateText = "空闲";
    String threadName = "Workbuddy 实时状态";
    String timeStr = "17:30:00";
    
    String alertTitle = "工作台空闲";
    String alertDesc = "等待任务指令...";
    
    String stepStr = "0/0";
    String toolsStr = "0 次";
    String durationStr = "00:00";
    String tokenStr = "0k";
    String todayTokenStr = "0m";
    String modelName = "";
    String networkStatus = "USB";
    String networkIp = "";
    int32_t networkRssi = 0;
    
    std::vector<TimelineItem> timeline;
};

class DisplayHud {
public:
    DisplayHud();
    bool init();
    void update(const HudData& data);
    void showBootScreen();
    void showSystemMessage(const String& title, const String& detail, uint16_t color);
    void testPanel();

private:
    LGFX_SzpS3 _tft;
    LGFX_Sprite _canvas; // 双缓冲画布 (320x240 in PSRAM)
    
    void drawHeader(const HudData& data);
    void drawAlertCard(const HudData& data);
    void drawMetricsGrid(const HudData& data);
    void drawTimeline(const HudData& data);
};
