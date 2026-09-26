const int SENSOR_PIN = A0;
const unsigned long SAMPLE_INTERVAL_US = 10000;
unsigned long nextSampleUs = 0;

void setup() {
    Serial.begin(115200);
    pinMode(SENSOR_PIN, INPUT);
    nextSampleUs = micros();
}

void loop() {
    unsigned long nowUs = micros();

    if ((long)(nowUs - nextSampleUs) >= 0) {
        nextSampleUs += SAMPLE_INTERVAL_US;

        int adcValue = analogRead(SENSOR_PIN);
        Serial.println(adcValue);
    }
}
