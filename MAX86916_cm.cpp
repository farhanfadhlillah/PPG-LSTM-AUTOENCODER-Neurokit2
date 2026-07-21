/**

@file MAX86916_cm.cpp
@brief Implementation file for MAX86916 class.
*/
#include <Arduino.h>
#include <Wire.h>
#include "MAX86916_cm.h"

/**

@brief Constructor for the MAX86916 class.
*/
MAX86916::MAX86916() {}
/**

@brief Initializes the MAX86916 sensor by configuring the I2C communication and verifying its identity.
@return Returns true if initialization was successful, false otherwise.
*/
boolean MAX86916::begin() {
// Start I2C communication.
Wire.begin();
Wire.setClock(I2C_SPEED_FAST);
// Verify that a MAX86916 sensor is connected by checking its part ID and revision ID.
if (read_Part_ID() != MAX86916_EXPECTED_PART_ID) {
// Error -- Part ID read from MAX86916 does not match expected part ID.
return false;
}
read_Revision_ID();

return true;
}


/*

@brief Sets up the MAX86916 sensor by configuring its parameters for particle sensing.
@param range The ADC range (in LSB) for the sensor.
@param powerLevel The LED pulse amplitude for the sensor.
@param sampleAverage The number of samples to average in the FIFO buffer.
@param ledMode The LED mode to use for the sensor (IR only, red and IR, all three LEDs).
@param sampleRate The sample rate for the sensor.
@param pulseWidth The pulse width for the LED.
@param adcRange The ADC range for the sensor.
*/

void MAX86916::setup(uint8_t range, uint8_t powerLevel, uint8_t sampleAverage, byte ledMode, uint8_t sampleRate, uint8_t pulseWidth, uint8_t adcRange) {
  softReset(); //Reset 

  //FIFO Configuration
  setFIFOAverage(sampleAverage);
  enableFIFORollover(); //Allow FIFO to roll over

  //Mode Configuration
  if (ledMode == 3) setLEDMode(MAX86916_MODE_FLEXLED); //Watch all three LED channels
  else if (ledMode == 2) setLEDMode(MAX86916_MODE_REDIRONLY); //Red and IR
  else setLEDMode(MAX86916_MODE_IRONLY); //IR only
  if (ledMode < 3) activeLEDs = ledMode; //Used to control how many bytes to read from FIFO buffer
  else if(ledMode == 3) activeLEDs = 4;
  else activeLEDs = ledMode;


  //Particle Sensing Configuration
  setADCRange(adcRange);
  setSampleRate(sampleRate);
  setPulseWidth(pulseWidth);


  //LED Pulse Amplitude Configuration
  
  setAllLEDRange(range);
  setPA_IR(powerLevel);
  setPA_RED(powerLevel);
  setPA_GREEN(powerLevel);
  setPA_BLUE(powerLevel);
  setPA_PROX(powerLevel);
 

  //Flex-LED Mode Configuration, Enable the reading of the three LEDs
  
  enableSlot(1, SLOT_IR_LED);
  if (ledMode > 1) enableSlot(2, SLOT_RED_LED);
  if (ledMode > 2){
    enableSlot(3, SLOT_GREEN_LED);
    enableSlot(4, SLOT_BLUE_LED);
  }
  
  clearFIFO(); //Reset the FIFO
}

/**
 * Performs a software reset on the MAX86916 sensor.
 * Writes a specific value to the MODECONFIG register to trigger the reset,
 * and then waits for the reset bit to be cleared, indicating that the reset is complete.
 * Includes a timeout of 100 milliseconds to prevent an infinite loop.
 */
void MAX86916::softReset() {
  mask(MAX86916_MODECONFIG, MAX86916_RESET_MASK, MAX86916_RESET);

  // Wait for bit to clear, indicating reset is complete
  unsigned long startTime = millis();
  while (millis() - startTime < 100)
  {
    uint8_t response = readRegister(MAX86916_I2C_ADDRESS, MAX86916_MODECONFIG);
    if ((response & MAX86916_RESET) == 0) break; // reset is complete
    delay(1); // don't overload I2C bus
  }
}

/**

Set the LED mode for the MAX86916 sensor
@param mode The LED mode to set
*/
void MAX86916::setLEDMode(uint8_t mode) {
mask(MAX86916_MODECONFIG, MAX86916_MODE_MASK, mode);
}
/**

Set the ADC range for the MAX86916 sensor
@param adcRange The ADC range to set
*/
void MAX86916::setADCRange(uint8_t adcRange) {
mask(MAX86916_MODECONFIG2, MAX86916_ADCRANGE_MASK, adcRange);
}
/**

Set the sample rate for the MAX86916 sensor
@param sampleRate The sample rate to set
*/
void MAX86916::setSampleRate(uint8_t sampleRate) {
mask(MAX86916_MODECONFIG2, MAX86916_SAMPLERATE_MASK, sampleRate);
}
/**

Set the pulse width for the MAX86916 sensor
@param pulseWidth The pulse width to set
*/
void MAX86916::setPulseWidth(uint8_t pulseWidth) {
mask(MAX86916_MODECONFIG2, MAX86916_PULSEWIDTH_MASK, pulseWidth);
}


/**

@brief Sets the LED range for a specific LED and updates the MAX86916_LED_RANGE register.
@param rangeMask: The mask corresponding to the LED whose range is being set.
@param range: The desired range value to set for the LED.
@retval None
*/
void MAX86916::setLEDRange(uint8_t rangeMask, uint8_t range) {
if(rangeMask == MAX86916_LED1_RGE_MASK) mask(MAX86916_LED_RANGE, rangeMask, range);
else if(rangeMask == MAX86916_LED2_RGE_MASK) mask(MAX86916_LED_RANGE, rangeMask, range << 2);
else if(rangeMask == MAX86916_LED3_RGE_MASK) mask(MAX86916_LED_RANGE, rangeMask, range << 4);
else if(rangeMask == MAX86916_LED4_RGE_MASK) mask(MAX86916_LED_RANGE, rangeMask, range << 6);
else mask(MAX86916_LED_RANGE, MAX86916_LED1_RGE_MASK, range);
}
/**

@brief Sets the LED range for all four LEDs and updates the MAX86916_LED_RANGE register.
@param range: The desired range value to set for all LEDs.
@retval None
*/
void MAX86916::setAllLEDRange(uint8_t range){
setLEDRange(MAX86916_LED1_RGE_MASK, range);
setLEDRange(MAX86916_LED2_RGE_MASK, range);
setLEDRange(MAX86916_LED3_RGE_MASK, range);
setLEDRange(MAX86916_LED4_RGE_MASK, range);
}

/**

Sets the amplitude of the IR pulse for the MAX86916's LED1.
@param amplitude The amplitude to set for the IR pulse.
*/
void MAX86916::setPA_IR(uint8_t amplitude) {
writeRegister(MAX86916_I2C_ADDRESS, MAX86916_LED1_PULSEAMP, amplitude);
}
/**

Sets the amplitude of the RED pulse for the MAX86916's LED2.
@param amplitude The amplitude to set for the RED pulse.
*/
void MAX86916::setPA_RED(uint8_t amplitude) {
writeRegister(MAX86916_I2C_ADDRESS, MAX86916_LED2_PULSEAMP, amplitude);
}
/**

Sets the amplitude of the GREEN pulse for the MAX86916's LED3.
@param amplitude The amplitude to set for the GREEN pulse.
*/
void MAX86916::setPA_GREEN(uint8_t amplitude) {
writeRegister(MAX86916_I2C_ADDRESS, MAX86916_LED3_PULSEAMP, amplitude);
}
/**

Sets the amplitude of the BLUE pulse for the MAX86916's LED4.
@param amplitude The amplitude to set for the BLUE pulse.
*/
void MAX86916::setPA_BLUE(uint8_t amplitude) {
writeRegister(MAX86916_I2C_ADDRESS, MAX86916_LED4_PULSEAMP, amplitude);
}
/**

Sets the amplitude of the proximity pulse for the MAX86916's LED_PROX.
@param amplitude The amplitude to set for the proximity pulse.
*/
void MAX86916::setPA_PROX(uint8_t amplitude) {
writeRegister(MAX86916_I2C_ADDRESS, MAX86916_LED_PROX_AMP, amplitude);
}
/**

Sets the threshold for detecting a proximity event.
@param threshMSB The threshold to set in the most significant byte.
*/
void MAX86916::setProximityThreshold(uint8_t threshMSB) {
writeRegister(MAX86916_I2C_ADDRESS, MAX86916_PROXINTTHRESH, threshMSB);
}
/**

Enables a specific LED slot on the MAX86916 device.
@param slotNumber The number of the slot to be enabled (1-4).
@param device The device to be used for the slot (0-15).
*/
void MAX86916::enableSlot(uint8_t slotNumber, uint8_t device) {
switch (slotNumber) {
// If slotNumber is 1, set the corresponding bit in MAX86916_LED_SEQREG1 to enable the slot.
case (1):
mask(MAX86916_LED_SEQREG1, MAX86916_SLOT1_MASK, device);
break;
// If slotNumber is 2, set the corresponding bit in MAX86916_LED_SEQREG1 to enable the slot (shifted left by 4 bits).
case (2):
mask(MAX86916_LED_SEQREG1, MAX86916_SLOT2_MASK, device << 4);
break;
// If slotNumber is 3, set the corresponding bit in MAX86916_LED_SEQREG2 to enable the slot.
case (3):
mask(MAX86916_LED_SEQREG2, MAX86916_SLOT3_MASK, device);
break;
// If slotNumber is 4, set the corresponding bit in MAX86916_LED_SEQREG2 to enable the slot (shifted left by 4 bits).
case (4):
mask(MAX86916_LED_SEQREG2, MAX86916_SLOT4_MASK, device << 4);
break;
// If slotNumber is not within the range of 1-4, do nothing (this should not happen).
default:
//Shouldn't be here!
break;
}
}

// FIFO Configuration
//

/**

Sets the number of samples to average in the FIFO on the MAX86916 device.
@param numberOfSamples The number of samples to average (0-7).
*/
void MAX86916::setFIFOAverage(uint8_t numberOfSamples) {
// Set the SAMPLEAVG bits in the FIFOCONFIG register to the specified number of samples.
mask(MAX86916_FIFOCONFIG, MAX86916_SAMPLEAVG_MASK, numberOfSamples);
}
/**

Clears the FIFO on the MAX86916 device.
*/
void MAX86916::clearFIFO() {
// Set the FIFO write and read pointers to 0 and clear the overflow flag to clear the FIFO.
writeRegister(MAX86916_I2C_ADDRESS, MAX86916_FIFO_WRITE_PTR, 0);
writeRegister(MAX86916_I2C_ADDRESS, MAX86916_FIFO_OVERFLOW, 0);
writeRegister(MAX86916_I2C_ADDRESS, MAX86916_FIFO_READ_PTR, 0);
}
/**

Enables FIFO rollover on the MAX86916 device.
*/
void MAX86916::enableFIFORollover() {
// Enable FIFO rollover by setting the ROLLOVER bit in the FIFOCONFIG register.
mask(MAX86916_FIFOCONFIG, MAX86916_ROLLOVER_MASK, MAX86916_ROLLOVER_ENABLE);
}

/**

Returns the current FIFO write pointer value on the MAX86916 device.
@return The current FIFO write pointer value.
*/
uint8_t MAX86916::getWritePointer() {
// Read the FIFO write pointer from the MAX86916 device and return its value.
return (readRegister(MAX86916_I2C_ADDRESS, MAX86916_FIFO_WRITE_PTR));
}
/**

Returns the current FIFO read pointer value on the MAX86916 device.
@return The current FIFO read pointer value.
*/
uint8_t MAX86916::getReadPointer() {
// Read the FIFO read pointer from the MAX86916 device and return its value.
return (readRegister(MAX86916_I2C_ADDRESS, MAX86916_FIFO_READ_PTR));
}
/**

Sets the proximity interrupt threshold on the MAX86916 device.
@param val The value to set the proximity interrupt threshold to.
*/
void MAX86916::setPROXINTTHRESH(uint8_t val) {
// Write the specified value to the PROXINTTHRESH register on the MAX86916 device.
writeRegister(MAX86916_I2C_ADDRESS, MAX86916_PROXINTTHRESH, val);
}
/**

Reads and returns the part ID register value on the MAX86916 device.
@return The part ID register value.
*/
uint8_t MAX86916::read_Part_ID() {
// Read and return the value of the PARTID register on the MAX86916 device.
return readRegister(MAX86916_I2C_ADDRESS, MAX86916_PARTID);
}
/**

Reads the revision ID register on the MAX86916 device and stores the value in the revisionID class member variable.
*/
void MAX86916::read_Revision_ID() {
// Read the value of the REVISIONID register on the MAX86916 device and store it in the revisionID member variable.
revisionID = readRegister(MAX86916_I2C_ADDRESS, MAX86916_REVISIONID);
}

/**

Returns the revision ID of the MAX86916 sensor.
@return The revision ID of the MAX86916 sensor.
*/
uint8_t MAX86916::getRevisionID() {
return revisionID;
}
/**

Returns the number of available samples in the data buffer.
@return The number of available samples in the data buffer.
*/
uint8_t MAX86916::available()
{
int8_t numberOfSamples = sensor_data_buffer.head - sensor_data_buffer.tail;
if (numberOfSamples < 0) numberOfSamples += STORAGE_SIZE;
return (numberOfSamples);
}

/**

Returns the most recent IR value from the MAX86916 sensor.
@return The most recent IR value from the MAX86916 sensor. Returns 0 if no new data is available.
*/
uint32_t MAX86916::getIR()
{
//Check the sensor for new data for 250ms
if(safeCheck(250))
return (sensor_data_buffer.IR[sensor_data_buffer.head]);
else
return(0); //Sensor failed to find new data
}


//Report the most recent red value
uint32_t MAX86916::getRed()
{
//Check the sensor for new data for 250ms
if(safeCheck(250))
return (sensor_data_buffer.red[sensor_data_buffer.head]);
else
return(0); //Sensor failed to find new data
}

//Report the most recent Green value
uint32_t MAX86916::getGreen()
{
//Check the sensor for new data for 250ms
if(safeCheck(250))
return (sensor_data_buffer.green[sensor_data_buffer.head]);
else
return(0); //Sensor failed to find new data
}

//Report the most recent Blue value
uint32_t MAX86916::getBlue()
{
//Check the sensor for new data for 250ms
if(safeCheck(250))
return (sensor_data_buffer.blue[sensor_data_buffer.head]);
else
return(0); //Sensor failed to find new data
}

uint32_t MAX86916::getGreenFast()
{
  return (sensor_data_buffer.green[sensor_data_buffer.head]);
}

uint32_t MAX86916::getBlueFast()
{
  return (sensor_data_buffer.blue[sensor_data_buffer.head]);
}


//Advance the tail
void MAX86916::nextSample()
{
  if(available()) //Only advance the tail if new data is available
  {
    sensor_data_buffer.tail++;
    sensor_data_buffer.tail %= STORAGE_SIZE; //Wrap condition
  }
}

/**
 * @brief Updates the head and tail pointers in the main struct if new data is available and returns the number of new samples obtained.
 * 
 * @return uint16_t The number of new samples obtained.
 */
uint16_t MAX86916::check()
{
  

  byte readPointer = getReadPointer();
  byte writePointer = getWritePointer();
 
	int numberOfSamples = 0;

  if (readPointer != writePointer)
  {
    //Calculate the number of readings we need to get from sensor
    numberOfSamples = writePointer - readPointer;
    if (numberOfSamples < 0) numberOfSamples += 32; //Wrap condition
    

    //We now have the number of readings, now calc bytes to read
    //For this example we are just doing Red and IR (3 bytes each)
    int bytesLeftToRead = numberOfSamples * activeLEDs * 3;

    //Get ready to read a burst of data from the FIFO register
    Wire.beginTransmission(MAX86916_I2C_ADDRESS);
    Wire.write(MAX86916_FIFO_DATA);
    Wire.endTransmission();

    //We may need to read as many as 288 bytes so we read in blocks no larger than I2C_BUFFER_LENGTH
    //I2C_BUFFER_LENGTH changes based on the platform. 64 bytes for SAMD21, 32 bytes for Uno.
    //Wire.requestFrom() is limited to BUFFER_LENGTH which is 32 on the Uno
    while (bytesLeftToRead > 0)
    {
      int toGet = bytesLeftToRead;
      if (toGet > I2C_BUFFER_LENGTH)
      {
        //If toGet is 32 this is bad because we read 6 bytes (IR+Red * 3 = 6) at a time
        //32 % 6 = 2 left over. We don't want to request 32 bytes, we want to request 30.
        //32 % 12 (IR+Red+GREEN+BLUE) = 8 left over. We want to request 24.

        toGet = I2C_BUFFER_LENGTH - (I2C_BUFFER_LENGTH % (activeLEDs * 3)); //Trim toGet to be a multiple of the samples we need to read
      }

      bytesLeftToRead -= toGet;

      //Request toGet number of bytes from sensor
      Wire.requestFrom(MAX86916_I2C_ADDRESS, toGet);
      
      while (toGet > 0)
      {
        sensor_data_buffer.head++; //Advance the head of the storage struct
        sensor_data_buffer.head %= STORAGE_SIZE; //Wrap condition

        byte temp[sizeof(uint32_t)]; //Array of 4 bytes that we will convert into long
        uint32_t tempLong;

        //Burst read three bytes - IR
        temp[3] = 0;
        temp[2] = Wire.read();
        temp[1] = Wire.read();
        temp[0] = Wire.read();

        //Convert array to long
        memcpy(&tempLong, temp, sizeof(tempLong));
    
    tempLong &= 0x3FFFF; //Zero out all but 18 bits

        sensor_data_buffer.IR[sensor_data_buffer.head] = tempLong; //Store this reading into the sensor_data_buffer array

        if (activeLEDs > 1)
        {
          //Burst read three more bytes - Red
          temp[3] = 0;
          temp[2] = Wire.read();
          temp[1] = Wire.read();
          temp[0] = Wire.read();

          //Convert array to long
          memcpy(&tempLong, temp, sizeof(tempLong));

      tempLong &= 0x3FFFF; //Zero out all but 18 bits
          
      sensor_data_buffer.red[sensor_data_buffer.head] = tempLong;
        }

        if (activeLEDs > 2)
        {
          //Burst read three more bytes - Green
          temp[3] = 0;
          temp[2] = Wire.read();
          temp[1] = Wire.read();
          temp[0] = Wire.read();

          //Convert array to long
          memcpy(&tempLong, temp, sizeof(tempLong));

      tempLong &= 0x3FFFF; //Zero out all but 18 bits

          sensor_data_buffer.green[sensor_data_buffer.head] = tempLong;

          //Burst read three more bytes - Blue
          temp[3] = 0;
          temp[2] = Wire.read();
          temp[1] = Wire.read();
          temp[0] = Wire.read();

          //Convert array to long
          memcpy(&tempLong, temp, sizeof(tempLong));

      tempLong &= 0x3FFFF; //Zero out all but 18 bits

          sensor_data_buffer.blue[sensor_data_buffer.head] = tempLong;
        }

        toGet -= activeLEDs * 3;
      }

    } //End while (bytesLeftToRead > 0)

  } //End readPtr != writePtr

  return (numberOfSamples); //Let the world know how much new data we found
}

/**

Check for new data from the MAX86916 sensor within a specified time period
@param maxTimeToCheck Maximum time to spend checking for new data in milliseconds
@return true if new data was found, false if new data was not found within the specified time
*/
bool MAX86916::safeCheck(uint8_t maxTimeToCheck)
{
  uint32_t markTime = millis();
  
  while(1)
  {
  if(millis() - markTime > maxTimeToCheck) return(false);

  if(check() ==true ) //We found new data!
    return(true);

  delay(1);
  }
}

// This function masks a specific register of the MAX86916 sensor
// by performing a bitwise AND with the provided mask and the current register value,
// then OR-ing with the provided data to set the masked bits to the desired value
// Inputs:
// - reg: the register to modify
// - mask: the bit mask to apply to the register
// - data: the data to write to the masked bits of the register
void MAX86916::mask(uint8_t reg, uint8_t mask, uint8_t data)
{
// Read the current value of the register
uint8_t originalContents = readRegister(MAX86916_I2C_ADDRESS, reg);

// Mask the relevant bits of the register
originalContents &= mask;

// Update the masked bits with the desired data
writeRegister(MAX86916_I2C_ADDRESS, reg, originalContents | data);
}

// This function reads the value of a specific register from the MAX86916 sensor
// Inputs:
// - address: the I2C address of the MAX86916 sensor
// - reg: the register to read
// Returns:
// - The value of the specified register
// - If reading the register fails, returns 0
uint8_t MAX86916::readRegister(uint8_t address, uint8_t reg) {
// Begin an I2C transmission to the specified address
Wire.beginTransmission(address);
// Write the register address to be read
Wire.write(reg);
// End the transmission but leave the bus active for a repeated start
Wire.endTransmission(false);

// Request 1 byte of data from the register
Wire.requestFrom((uint8_t)address, (uint8_t)1);
// If the requested data is available, return it
if (Wire.available())
{
return(Wire.read());
}

// If the requested data is not available, return 0 to indicate failure
return (0);
}

// This function writes a value to a specific register on the MAX86916 sensor
// Inputs:
// - address: the I2C address of the MAX86916 sensor
// - reg: the register to write
// - value: the value to write to the specified register
void MAX86916::writeRegister(uint8_t address, uint8_t reg, uint8_t value) {
// Begin an I2C transmission to the specified address
Wire.beginTransmission(address);
// Write the register address to be written to
Wire.write(reg);
// Write the value to be written to the specified register
Wire.write(value);
// End the I2C transmission
Wire.endTransmission();
}

// Get the value of the overflow counter register
uint8_t MAX86916::getOverflowCounter() {
return (readRegister(MAX86916_I2C_ADDRESS, MAX86916_FIFO_OVERFLOW));
}

// Get the number of samples in the FIFO buffer
uint16_t MAX86916::nr_sample_FIFO()
{
byte readPointer = getReadPointer();
byte writePointer = getWritePointer();
byte overflowCounter = getOverflowCounter();
int numberOfSamples = 0;

// Check if new data is available
if (overflowCounter == 0) // No overflow has occurred
{
if (writePointer > readPointer)
{
numberOfSamples = writePointer - readPointer;
}
else
{
numberOfSamples = writePointer - readPointer + 32;
}
}
else
{
numberOfSamples = 32;
}

return (numberOfSamples);
}
