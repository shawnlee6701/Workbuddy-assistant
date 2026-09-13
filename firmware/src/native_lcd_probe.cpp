#include "native_lcd_probe.h"
#include "bsp_board.h"

#include <Arduino.h>
#include "driver/spi_master.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"

static esp_lcd_panel_handle_t panel = nullptr;
static uint16_t* frame = nullptr;

static bool check(esp_err_t err, const char* step) {
    Serial.printf("[LCD-NATIVE] %s -> %s\n", step, esp_err_to_name(err));
    return err == ESP_OK;
}

bool nativeLcdProbe() {
    const spi_bus_config_t bus = {
        .mosi_io_num = GPIO_NUM_40,
        .miso_io_num = GPIO_NUM_NC,
        .sclk_io_num = GPIO_NUM_41,
        .quadwp_io_num = GPIO_NUM_NC,
        .quadhd_io_num = GPIO_NUM_NC,
        .data4_io_num = GPIO_NUM_NC,
        .data5_io_num = GPIO_NUM_NC,
        .data6_io_num = GPIO_NUM_NC,
        .data7_io_num = GPIO_NUM_NC,
        .max_transfer_sz = 320 * 240 * 2,
        .flags = SPICOMMON_BUSFLAG_MASTER,
        .intr_flags = 0,
    };
    if (!check(spi_bus_initialize(SPI3_HOST, &bus, SPI_DMA_CH_AUTO), "spi_bus_initialize")) return false;

    esp_lcd_panel_io_handle_t io = nullptr;
    const esp_lcd_panel_io_spi_config_t ioConfig = {
        .cs_gpio_num = GPIO_NUM_NC,
        .dc_gpio_num = GPIO_NUM_39,
        .spi_mode = 2,
        .pclk_hz = 10 * 1000 * 1000,
        .trans_queue_depth = 10,
        .on_color_trans_done = nullptr,
        .user_ctx = nullptr,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .flags = {},
    };
    if (!check(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)SPI3_HOST, &ioConfig, &io), "new_panel_io")) return false;

    const esp_lcd_panel_dev_config_t panelConfig = {
        .reset_gpio_num = GPIO_NUM_NC,
        .color_space = ESP_LCD_COLOR_SPACE_RGB,
        .bits_per_pixel = 16,
        .flags = {},
        .vendor_config = nullptr,
    };
    if (!check(esp_lcd_new_panel_st7789(io, &panelConfig, &panel), "new_st7789")) return false;
    if (!check(esp_lcd_panel_reset(panel), "panel_reset")) return false;
    if (!BSPBoard::selectLcd()) return false;
    delay(20);
    if (!check(esp_lcd_panel_init(panel), "panel_init")) return false;
    if (!check(esp_lcd_panel_invert_color(panel, true), "invert")) return false;
    if (!check(esp_lcd_panel_swap_xy(panel, true), "swap_xy")) return false;
    if (!check(esp_lcd_panel_mirror(panel, true, false), "mirror")) return false;
    if (!check(esp_lcd_panel_disp_on_off(panel, true), "display_on")) return false;

    frame = (uint16_t*)heap_caps_malloc(320 * 240 * 2, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    if (!frame) {
        Serial.println("[LCD-NATIVE] internal DMA frame allocation failed");
        return false;
    }
    for (int y = 0; y < 240; ++y) {
        uint16_t color = y < 60 ? 0xF800 : y < 120 ? 0x07E0 : y < 180 ? 0x001F : 0xFFFF;
        for (int x = 0; x < 320; ++x) frame[y * 320 + x] = color;
    }
    return check(esp_lcd_panel_draw_bitmap(panel, 0, 0, 320, 240, frame), "draw_color_bars");
}

bool nativeLcdDraw(const void* pixels) {
    if (!panel || !frame || !pixels) return false;
    memcpy(frame, pixels, 320 * 240 * 2);
    return esp_lcd_panel_draw_bitmap(panel, 0, 0, 320, 240, frame) == ESP_OK;
}
