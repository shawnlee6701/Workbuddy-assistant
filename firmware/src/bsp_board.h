#pragma once
#include <Arduino.h>
#include <Wire.h>
#define LGFX_USE_V1
#include <LovyanGFX.hpp>

// ==================== 立创·实战派 ESP32-S3 引脚定义 ====================
#define PIN_I2C_SDA         1
#define PIN_I2C_SCL         2

#define PIN_LCD_MOSI        40
#define PIN_LCD_SCLK        41
#define PIN_LCD_DC          39
#define PIN_LCD_BL          42   // 背光：低电平点亮 (LOW = ON)

#define PIN_USER_KEY        0    // BOOT 用户按键

// PCA9557 寄存器与 IO 掩码
#define PCA9557_ADDR_DEFAULT 0x19
#define PCA9557_REG_INPUT    0x00
#define PCA9557_REG_OUTPUT   0x01
#define PCA9557_REG_POLARITY 0x02
#define PCA9557_REG_CONFIG   0x03

#define PCA_IO_LCD_CS       (1 << 0)  // IO0: LCD 片选 (低有效)
#define PCA_IO_PA_EN        (1 << 1)  // IO1: 功放使能 (高有效)
#define PCA_IO_DVP_PWDN     (1 << 2)  // IO2: 摄像头电源

// ==================== LovyanGFX 自定义显示类 ====================
class SzpST7789 : public lgfx::Panel_ST7789 {
protected:
    const uint8_t* getInitCommands(uint8_t listno) const override {
        // 本板无独立 LCD reset GPIO，必须发送 ST7789 软件复位。
        static constexpr uint8_t reset[] = {0x01, 0x80, 150, 0xFF, 0xFF};
        if (listno == 0) return reset;
        return lgfx::Panel_ST7789::getInitCommands(listno - 1);
    }
};

class LGFX_SzpS3 : public lgfx::LGFX_Device {
    SzpST7789               _panel_instance;
    lgfx::Bus_SPI           _bus_instance;

public:
    LGFX_SzpS3() {
        {
            auto cfg = _bus_instance.config();
            cfg.spi_host = SPI3_HOST;
            cfg.spi_mode = 2; // 立创实战派官方 LCD 时序
            cfg.freq_write = 10000000;
            cfg.freq_read  = 16000000;
            cfg.spi_3wire  = true;
            cfg.use_lock   = true;
            cfg.dma_channel = SPI_DMA_CH_AUTO;
            cfg.pin_sclk = PIN_LCD_SCLK;
            cfg.pin_mosi = PIN_LCD_MOSI;
            cfg.pin_miso = -1;
            cfg.pin_dc   = PIN_LCD_DC;
            _bus_instance.config(cfg);
            _panel_instance.setBus(&_bus_instance);
        }

        {
            auto cfg = _panel_instance.config();
            cfg.pin_cs           = -1; // CS 硬件由 PCA9557 持续拉低
            cfg.pin_rst          = -1;
            cfg.pin_busy         = -1;
            cfg.panel_width      = 240;
            cfg.panel_height     = 320;
            cfg.offset_x         = 0;
            cfg.offset_y         = 0;
            cfg.offset_rotation  = 0;
            cfg.dummy_read_pixel = 8;
            cfg.dummy_read_bits  = 1;
            cfg.readable         = false;
            cfg.invert           = true;
            cfg.rgb_order        = false;
            cfg.dlen_16bit       = false;
            cfg.bus_shared       = false;
            _panel_instance.config(cfg);
        }

        setPanel(&_panel_instance);
    }
};

class BSPBoard {
public:
    static bool init();
    static void setBacklight(bool on);
    static bool selectLcd();
    static bool isKeyPressed();
    static uint8_t pca9557Addr;

private:
    static bool initPCA9557();
};
