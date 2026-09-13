#include "bsp_board.h"

uint8_t BSPBoard::pca9557Addr = PCA9557_ADDR_DEFAULT;

static bool writePCA9557Reg(uint8_t reg, uint8_t val) {
    Wire.beginTransmission(BSPBoard::pca9557Addr);
    Wire.write(reg);
    Wire.write(val);
    return (Wire.endTransmission() == 0);
}

bool BSPBoard::initPCA9557() {
    // 扫描 I2C 地址
    Serial.println("[BSP] Scanning I2C bus...");
    bool found = false;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            Serial.printf("[BSP] Found I2C device at 0x%02X\n", addr);
            if (addr == 0x19 || addr == 0x18) {
                pca9557Addr = addr;
                found = true;
            }
        }
    }

    if (!found) {
        Serial.println("[BSP] ERROR: LCD IO expander not detected");
        return false;
    }

    // 配置 PCA9557: IO0(LCD_CS), IO1(PA_EN), IO2(DVP_PWDN) 为输出 (0为输出)
    bool preset = writePCA9557Reg(PCA9557_REG_OUTPUT, 0x05);
    bool ok1 = writePCA9557Reg(PCA9557_REG_CONFIG, 0xF8);
    // LCD_CS 先保持高电平，LCD 驱动完成 reset 后再选中。
    Serial.printf("[BSP] PCA9557 init at 0x%02X -> %s\n", pca9557Addr, (preset && ok1) ? "SUCCESS" : "FAILED");
    return (preset && ok1);
}

bool BSPBoard::init() {
    // 1. 初始化按键
    pinMode(PIN_USER_KEY, INPUT_PULLUP);

    // 2. 初始化并立即点亮背光 (实战派低电平点亮)
    pinMode(PIN_LCD_BL, OUTPUT);
    digitalWrite(PIN_LCD_BL, LOW); // 点亮背光

    // 3. 初始化 I2C 总线
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, 100000);
    delay(100);

    // 4. 初始化 PCA9557 芯片拉低 LCD_CS
    bool pcaOk = initPCA9557();

    return pcaOk;
}

void BSPBoard::setBacklight(bool on) {
    digitalWrite(PIN_LCD_BL, on ? LOW : HIGH);
}

bool BSPBoard::selectLcd() {
    // LCD_CS=0, PA_EN=0, DVP_PWDN=1
    bool ok = writePCA9557Reg(PCA9557_REG_OUTPUT, PCA_IO_DVP_PWDN);
    Serial.printf("[BSP] LCD_CS low -> %s\n", ok ? "SUCCESS" : "FAILED");
    return ok;
}

bool BSPBoard::isKeyPressed() {
    return (digitalRead(PIN_USER_KEY) == LOW);
}
