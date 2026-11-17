/*
 * Asistente de voz con ESP32-S3 — firmware de REFERENCIA
 * ------------------------------------------------------
 * Hace en hardware real lo mismo que el "ESP32 virtual" de la carpeta web/:
 *   1. Conecta a Wi-Fi.
 *   2. Detecta el pulsador.
 *   3. Graba con el INMP441 (I2S) a 16 kHz, 16 bits, mono, mientras el botón esté presionado.
 *   4. Envía el WAV por HTTP POST al servidor Python, con token.
 *   5. Recibe el WAV de respuesta.
 *   6. Lo reproduce con el MAX98357A (I2S).
 *
 * NOTA: este código no se ha probado en una placa física (la práctica se hizo de forma
 * virtual). Sirve como punto de partida si se consigue el hardware.
 *
 * Requisitos: Arduino IDE + núcleo "esp32" de Espressif 3.x (trae ESP_I2S.h).
 * Placa: "ESP32S3 Dev Module", PSRAM: "OPI PSRAM" (para módulos N16R8).
 * Copia secrets.h.example como secrets.h y completa tus datos (no lo subas al repositorio).
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ESP_I2S.h>
#include "secrets.h"  // WIFI_SSID, WIFI_PASS, SERVIDOR_URL, DEVICE_TOKEN

// ---------------- Pines (ajústalos a tu montaje) ----------------
#define PIN_BOTON   4   // pulsador a GND (se usa el pull-up interno)
#define MIC_SCK     5   // INMP441 SCK
#define MIC_WS      6   // INMP441 WS
#define MIC_SD      7   // INMP441 SD   (L/R del INMP441 a GND = canal izquierdo)
#define AMP_BCLK   15   // MAX98357A BCLK
#define AMP_LRC    16   // MAX98357A LRC
#define AMP_DIN    17   // MAX98357A DIN

// ---------------- Parámetros ----------------
const uint32_t FRECUENCIA   = 16000;
const uint32_t MAX_SEGUNDOS = 10;          // igual que MAX_SEGUNDOS_GRABACION del servidor
const uint32_t MIN_MS       = 400;         // pulsaciones más cortas se ignoran
const size_t   CABECERA_WAV = 44;
const size_t   MAX_GRABACION = CABECERA_WAV + FRECUENCIA * 2 * MAX_SEGUNDOS;
const size_t   MAX_RESPUESTA = 1024 * 1024; // 1 MB ≈ 32 s de audio a 16 kHz

I2SClass mic;
I2SClass amp;
uint8_t *grabacion = nullptr;  // en PSRAM
uint8_t *respuesta = nullptr;  // en PSRAM

// ----------------------------------------------------------------- utilidades

void escribirCabeceraWav(uint8_t *b, uint32_t bytesDatos) {
  auto u32 = [&](int o, uint32_t v) { memcpy(b + o, &v, 4); };
  auto u16 = [&](int o, uint16_t v) { memcpy(b + o, &v, 2); };
  memcpy(b, "RIFF", 4);      u32(4, 36 + bytesDatos);  memcpy(b + 8, "WAVE", 4);
  memcpy(b + 12, "fmt ", 4); u32(16, 16); u16(20, 1);  u16(22, 1);
  u32(24, FRECUENCIA);       u32(28, FRECUENCIA * 2);  u16(32, 2); u16(34, 16);
  memcpy(b + 36, "data", 4); u32(40, bytesDatos);
}

void pitidoError() {  // sonido local cuando no hay audio del servidor
  const int n = FRECUENCIA / 5;
  static int16_t tono[FRECUENCIA / 5];
  for (int f : {440, 330}) {
    for (int i = 0; i < n; i++) tono[i] = (int16_t)(6000 * sin(2 * PI * f * i / FRECUENCIA));
    amp.write((uint8_t *)tono, n * 2);
  }
}

void conectarWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Conectando a Wi-Fi \"%s\"", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) { delay(250); Serial.print('.'); }
  if (WiFi.status() == WL_CONNECTED) Serial.printf("\nWi-Fi conectado. IP: %s\n", WiFi.localIP().toString().c_str());
  else Serial.println("\nNo se pudo conectar al Wi-Fi");
}

// ----------------------------------------------------------------- grabación

size_t grabarMientrasPresionado() {
  int32_t bloque[256];  // el INMP441 entrega 24 bits dentro de palabras de 32 bits
  int16_t *pcm = (int16_t *)(grabacion + CABECERA_WAV);
  size_t muestras = 0;
  const size_t maxMuestras = FRECUENCIA * MAX_SEGUNDOS;
  uint32_t inicio = millis();

  Serial.println("Botón presionado -> grabando...");
  while (digitalRead(PIN_BOTON) == LOW && muestras < maxMuestras) {
    size_t leidos = mic.readBytes((char *)bloque, sizeof(bloque)) / 4;
    for (size_t i = 0; i < leidos && muestras < maxMuestras; i++) {
      int32_t v = bloque[i] >> 14;              // 24 bits útiles -> 16 bits con algo de ganancia
      pcm[muestras++] = (int16_t)constrain(v, -32768, 32767);
    }
  }
  uint32_t ms = millis() - inicio;
  if (ms < MIN_MS) { Serial.println("Pulsación muy corta, se ignora."); return 0; }
  escribirCabeceraWav(grabacion, muestras * 2);
  Serial.printf("Grabación: %.2f s, %u muestras\n", muestras / (float)FRECUENCIA, (unsigned)muestras);
  return CABECERA_WAV + muestras * 2;
}

// ----------------------------------------------------------------- envío y reproducción

void reproducirWav(uint8_t *wav, size_t largo) {
  // Busca el bloque "data" (la cabecera puede no medir exactamente 44 bytes)
  for (size_t i = 12; i + 8 < largo && i < 200; i++) {
    if (memcmp(wav + i, "data", 4) == 0) {
      size_t inicio = i + 8;
      Serial.printf("Reproduciendo %.2f s de audio\n", (largo - inicio) / (2.0 * FRECUENCIA));
      amp.write(wav + inicio, largo - inicio);
      return;
    }
  }
  Serial.println("La respuesta no tiene un WAV válido");
  pitidoError();
}

void consultar(size_t largo) {
  conectarWifi();
  if (WiFi.status() != WL_CONNECTED) { pitidoError(); return; }

  HTTPClient http;
  const char *cabeceras[] = {"Content-Type", "X-Estado", "X-Error", "X-Tiempos"};
  http.begin(String(SERVIDOR_URL) + "/api/consulta");
  http.setTimeout(60000);
  http.collectHeaders(cabeceras, 4);
  http.addHeader("Content-Type", "audio/wav");
  http.addHeader("Authorization", String("Bearer ") + DEVICE_TOKEN);
  http.addHeader("X-Dispositivo", WiFi.macAddress());

  uint32_t t0 = millis();
  Serial.printf("HTTP POST (%u bytes)...\n", (unsigned)largo);
  int codigo = http.POST(grabacion, largo);
  Serial.printf("HTTP %d en %lu ms · estado=%s %s\n", codigo, millis() - t0,
                http.header("X-Estado").c_str(), http.header("X-Error").c_str());

  if (codigo <= 0 || !http.header("Content-Type").startsWith("audio/wav")) {
    Serial.printf("Sin audio del servidor (%s)\n", http.errorToString(codigo).c_str());
    http.end();
    pitidoError();
    return;
  }

  // Descargar la respuesta a PSRAM
  String tiempos = http.header("X-Tiempos");
  int total = http.getSize();
  WiFiClient *flujo = http.getStreamPtr();
  size_t recibidos = 0;
  uint32_t ultimo = millis();
  while (http.connected() && (total < 0 || recibidos < (size_t)total) && recibidos < MAX_RESPUESTA) {
    size_t disponibles = flujo->available();
    if (disponibles) {
      recibidos += flujo->readBytes(respuesta + recibidos, min(disponibles, MAX_RESPUESTA - recibidos));
      ultimo = millis();
    } else if (millis() - ultimo > 5000) {
      break;
    } else {
      delay(1);
    }
  }
  http.end();
  Serial.printf("Tiempo hasta reproducir: %lu ms · tiempos servidor: %s\n", millis() - t0, tiempos.c_str());
  reproducirWav(respuesta, recibidos);  // en errores es el mensaje de voz del servidor
}

// ----------------------------------------------------------------- setup / loop

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\nAsistente de voz ESP32-S3 v1.0");
  pinMode(PIN_BOTON, INPUT_PULLUP);

  grabacion = (uint8_t *)ps_malloc(MAX_GRABACION);
  respuesta = (uint8_t *)ps_malloc(MAX_RESPUESTA);
  if (!grabacion || !respuesta) {
    Serial.println("ERROR: no hay PSRAM suficiente (¿activaste OPI PSRAM?)");
    while (true) delay(1000);
  }

  mic.setPins(MIC_SCK, MIC_WS, -1, MIC_SD);
  if (!mic.begin(I2S_MODE_STD, FRECUENCIA, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT))
    Serial.println("ERROR iniciando I2S del micrófono");

  amp.setPins(AMP_BCLK, AMP_LRC, AMP_DIN);
  if (!amp.begin(I2S_MODE_STD, FRECUENCIA, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO))
    Serial.println("ERROR iniciando I2S del amplificador");

  conectarWifi();
  Serial.println("Listo. Mantén presionado el botón para hablar.");
}

void loop() {
  if (digitalRead(PIN_BOTON) == LOW) {
    delay(20);  // antirrebote
    if (digitalRead(PIN_BOTON) == LOW) {
      size_t largo = grabarMientrasPresionado();
      if (largo) consultar(largo);
      while (digitalRead(PIN_BOTON) == LOW) delay(10);  // esperar a que suelte
      Serial.println("Listo para otra consulta.");
    }
  }
  delay(5);
}
