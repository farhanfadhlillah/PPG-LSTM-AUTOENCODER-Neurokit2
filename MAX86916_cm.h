
#ifndef MAX86916_cm_H
#define MAX86916_cm_H



#include <Arduino.h>
#include <Wire.h>
#include "MAX86916_Registers.h"

#define STORAGE_SIZE 4 //Each long is 4 bytes
#define I2C_SPEED_STANDARD        100000
#define I2C_SPEED_FAST            400000

//Define the size of the I2C buffer based on the platform the user has
#if defined(__AVR_ATmega328P__) || defined(__AVR_ATmega168__)

  //I2C_BUFFER_LENGTH is defined in Wire.H
  #define I2C_BUFFER_LENGTH BUFFER_LENGTH

#elif defined(__SAMD21G18A__)

  //SAMD21 uses RingBuffer.h
  #define I2C_BUFFER_LENGTH SERIAL_BUFFER_SIZE

#else

  //The catch-all default is 32
  #define I2C_BUFFER_LENGTH 32

#endif

class MAX86916 {
 public: 
  MAX86916();

  boolean begin();
  // Fast getters (no safeCheck). Return last sample already in buffer.
  uint32_t getGreenFast();
  uint32_t getBlueFast();
  uint32_t getIR(void); //Returns immediate IR value
  uint32_t getRed(void); //Returns immediate Red value
  uint32_t getGreen(void); //Returns immediate Green value
  uint32_t getBlue(void); //Returns immediate Blue value
  bool safeCheck(uint8_t maxTimeToCheck); //Given a max amount of time, check for new data

  // Configuration
  void softReset();
  void shutDown(); 
  void wakeUp(); 

  void setLEDMode(uint8_t mode);

  void setADCRange(uint8_t adcRange);
  void setSampleRate(uint8_t sampleRate);
  void setPulseWidth(uint8_t pulseWidth);
  void setLEDRange(uint8_t rangeMask, uint8_t range);
  void setAllLEDRange(uint8_t range);

  void setPA_IR(uint8_t value);
  void setPA_RED(uint8_t value);
  void setPA_GREEN(uint8_t value);
  void setPA_BLUE(uint8_t value);
  void setPA_PROX(uint8_t value);

  void setProximityThreshold(uint8_t threshMSB);

  //Multi-led configuration mode (page 22)
  void enableSlot(uint8_t slotNumber, uint8_t device); //Given slot number, assign a device to slot
  void disableSlots(void);
  
  // Data Collection

  //Interrupts (page 13, 14)
  uint8_t get_INT_1(); //Returns the main interrupt group
  void enable_A_FULL(); //Enable/disable individual interrupts
  void disable_A_FULL();
  void enable_DATA_RDY();
  void disable_DATA_RDY();
  void enable_ALC_OVF();
  void disable_ALC_OVF(void);
  void enable_PROX_INT(void);
  void disable_PROX_INT(void);
  void enableDIETEMPRDY(void);
  void disableDIETEMPRDY(void);

  //FIFO Configuration (page 18)
  void setFIFOAverage(uint8_t samples);
  void enableFIFORollover();
  void disableFIFORollover();
  void setFIFOAlmostFull(uint8_t samples);
  
  //FIFO Reading
  uint16_t check(void); //Checks for new data and fills FIFO
  uint8_t available(void); //Tells caller how many new samples are available (head - tail)
  void nextSample(void); //Advances the tail of the sensor_data_buffer array
  uint32_t getFIFOIR(void); //Returns the FIFO sample pointed to by tail
  uint32_t getFIFORed(void); //Returns the FIFO sample pointed to by tail
  uint32_t getFIFOGreen(void); //Returns the FIFO sample pointed to by tail
  uint32_t getFIFOBlue(void); //Returns the FIFO sample pointed to by tail

  uint8_t getWritePointer(void);
  uint8_t getReadPointer(void);
  uint8_t getOverflowCounter();
  uint16_t nr_sample_FIFO();
  void clearFIFO(void); //Sets the read/write pointers to zero

  //Proximity Mode Interrupt Threshold
  void setPROXINTTHRESH(uint8_t val);

  // Detecting ID/Revision
  uint8_t getRevisionID();
  uint8_t read_Part_ID();  

  // Setup the IC with user selectable settings
  void setup(uint8_t range = 0, uint8_t powerLevel = 0x1F, uint8_t sampleAverage = MAX86916_SAMPLEAVG_4, byte ledMode = 3, uint8_t sampleRate = MAX86916_SAMPLERATE_400, uint8_t pulseWidth = MAX86916_PULSEWIDTH_420, uint8_t adcRange = MAX86916_ADCRANGE_16384);

  // Low-level I2C communication
  uint8_t readRegister(uint8_t address, uint8_t reg);
  void writeRegister(uint8_t address, uint8_t reg, uint8_t value);

 private:

  //activeLEDs is the number of channels turned on, and can be 1 to 4. 2 is common for Red+IR.
  byte activeLEDs; //Gets set during setup. Allows check() to calculate how many bytes to read from FIFO
  
  uint8_t revisionID; 

  void read_Revision_ID();

  void mask(uint8_t reg, uint8_t mask, uint8_t data);
 
   
  typedef struct Record
  {
    uint32_t IR[STORAGE_SIZE];
    uint32_t red[STORAGE_SIZE];
    uint32_t green[STORAGE_SIZE];
    uint32_t blue[STORAGE_SIZE];
    byte head;
    byte tail;
  } sensor_data_buffer_struct; //This is our circular buffer of readings from the sensor

  sensor_data_buffer_struct sensor_data_buffer;

};



#endif
