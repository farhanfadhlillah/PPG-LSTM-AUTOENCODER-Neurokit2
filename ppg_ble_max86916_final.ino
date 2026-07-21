#include <Wire.h>
#include <MAX86916_cm.h>
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEServer.h>
#include <BLE2902.h>
#include <WiFi.h>

#define SERVICE_UUID         "12345678-1234-1234-1234-1234567890ab"
#define CHARACTERISTIC_UUID  "abcd1234-5678-1234-5678-1234567890ab"

const char* AP_SSID = "PPG_FATIGUE_AP";
const char* AP_PASS = "12345678";   // minimal 8 karakter

MAX86916 Sensor;

BLEServer* pServer = nullptr;
BLECharacteristic* pCharacteristic = nullptr;
bool deviceConnected = false;

class MyServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) override {
    deviceConnected = true;
  }

  void onDisconnect(BLEServer* pServer) override {
    deviceConnected = false;
    BLEDevice::startAdvertising();
  }
};

struct __attribute__((packed)) Sample {
  uint32_t t_us;
  uint32_t green;
  uint32_t blue;
};

static const uint16_t BATCH_N = 10;
Sample batch[BATCH_N];
int batchIdx = 0;

uint32_t sampleCount = 0;
uint32_t notifyCount = 0;
uint32_t lastDbgMs = 0;
uint32_t lastWiFiCheckMs = 0;

void startWiFiAP() {
  WiFi.persistent(false);
  WiFi.disconnect(true, true);
  delay(200);

  WiFi.mode(WIFI_AP);
  WiFi.setSleep(false);   // biar radio tetap aktif, tidak hemat daya

  bool ok = WiFi.softAP(AP_SSID, AP_PASS);

  if (ok) {
    Serial.println("WiFi AP started");
    Serial.print("SSID   : ");
    Serial.println(AP_SSID);
    Serial.print("AP IP  : ");
    Serial.println(WiFi.softAPIP());
  } else {
    Serial.println("Failed to start WiFi AP");
  }
}

void ensureWiFiAPAlive() {
  if (millis() - lastWiFiCheckMs < 3000) return;
  lastWiFiCheckMs = millis();

  wifi_mode_t mode = WiFi.getMode();

  // Kalau mode bukan AP, atau AP IP invalid, start ulang
  if (mode != WIFI_AP && mode != WIFI_AP_STA) {
    Serial.println("WiFi AP lost, restarting...");
    startWiFiAP();
    return;
  }

  IPAddress ip = WiFi.softAPIP();
  if (ip[0] == 0) {
    Serial.println("WiFi AP IP invalid, restarting...");
    startWiFiAP();
  }
}

void setup() {
  Serial.begin(115200);

  uint32_t t0 = millis();
  while (!Serial && (millis() - t0 < 1000)) {}

  Wire.begin(8, 9);
  Wire.setClock(1000000); // kalau tidak stabil, ganti 400000

  if (!Sensor.begin()) {
    Serial.println("Sensor not found. Check wiring.");
    while (true) {}
  }

  Sensor.setup(
    0,
    0x1F,
    MAX86916_SAMPLEAVG_1,
    3,
    MAX86916_SAMPLERATE_400,
    MAX86916_PULSEWIDTH_120,
    MAX86916_ADCRANGE_16384
  );

  // WiFi AP selalu aktif
  startWiFiAP();

  BLEDevice::init("PPG_FATIGUE");
  BLEDevice::setMTU(247);

  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());

  BLEService* pService = pServer->createService(SERVICE_UUID);

  pCharacteristic = pService->createCharacteristic(
    CHARACTERISTIC_UUID,
    BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ
  );
  pCharacteristic->addDescriptor(new BLE2902());

  pService->start();
  BLEDevice::getAdvertising()->start();

  Serial.println("BLE ready. FIFO + binary batch mode.");
}

void loop() {
  // pastikan WiFi AP tetap hidup
  ensureWiFiAPAlive();

  // Ambil data baru dari FIFO sensor
  Sensor.check();

  // Proses semua sample yang tersedia
  while (Sensor.available()) {
    batch[batchIdx].t_us  = micros();
    batch[batchIdx].green = Sensor.getGreenFast();
    batch[batchIdx].blue  = Sensor.getBlueFast();
    batchIdx++;
    sampleCount++;

    Sensor.nextSample();

    if (batchIdx >= BATCH_N) {
      if (deviceConnected) {
        pCharacteristic->setValue((uint8_t*)batch, sizeof(batch));
        pCharacteristic->notify();
        notifyCount++;
      }
      batchIdx = 0;
    }
  }

  uint32_t nowMs = millis();
  if (nowMs - lastDbgMs >= 1000) {
    lastDbgMs = nowMs;
    Serial.printf(
      "sample_rate=%lu Hz | notify=%lu pkt/s | BLE=%d | AP clients=%d | AP IP=%s\n",
      (unsigned long)sampleCount,
      (unsigned long)notifyCount,
      deviceConnected ? 1 : 0,
      WiFi.softAPgetStationNum(),
      WiFi.softAPIP().toString().c_str()
    );
    sampleCount = 0;
    notifyCount = 0;
  }
}