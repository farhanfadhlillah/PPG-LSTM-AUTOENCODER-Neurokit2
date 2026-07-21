/* Registers MAX86916*/
#define MAX86916_I2C_ADDRESS 	 0x57
#define EXPECTED_PART_ID		 0x2B


#include <Arduino.h>
#include <Wire.h>


// Status Registers
#define MAX86916_INT_STAT_1 		0x00
#define MAX86916_INT_EN_1			0x02

// FIFO Registers
#define MAX86916_FIFO_WRITE_PTR 	0x04
#define MAX86916_FIFO_OVERFLOW 		0x05
#define MAX86916_FIFO_READ_PTR 		0x06
#define MAX86916_FIFO_DATA			0x07

// Configuration Registers
#define MAX86916_FIFOCONFIG  		0x08
#define MAX86916_MODECONFIG  		0x09
#define MAX86916_MODECONFIG2 		0x0A

//led pulse amplitude registers    
#define MAX86916_LED1_PULSEAMP  	0x0C
#define MAX86916_LED2_PULSEAMP 		0x0D
#define MAX86916_LED3_PULSEAMP  	0x0E
#define MAX86916_LED4_PULSEAMP  	0x0F
#define MAX86916_LED_RANGE  		0x11
#define MAX86916_LED_PROX_AMP  		0x12

//led sequence control registers
#define MAX86916_LED_SEQREG1  		0x13
#define MAX86916_LED_SEQREG2  		0x14

//Cross talk DAC registers
#define MAX86916_CROSSTALK1  		0x26
#define MAX86916_CROSSTALK2  		0x27
#define MAX86916_CROSSTALK3  		0x28
#define MAX86916_CROSSTALK4  		0x29

// Proximity Mode Registers
#define MAX86916_PROXINTTHRESH 		0x30

// LED Connectivity Test Registers
#define MAX86916_COMPARENABLE  		0x31
#define MAX86916_COMPARSTATUS  		0x32

// Part ID Registers
#define MAX86916_REVISIONID 		0xFE
#define MAX86916_PARTID  			0xFF  





//PARAMETERS
// Interrupt configuration 
#define MAX86916_INT_A_FULL_MASK 				(byte)~0b10000000
#define MAX86916_INT_A_FULL_ENABLE  			0x80
#define MAX86916_INT_A_FULL_DISABLE  			0x00

#define MAX86916_INT_DATA_RDY_MASK  			(byte)~0b01000000
#define MAX86916_INT_DATA_RDY_ENABLE 			0x40
#define MAX86916_INT_DATA_RDY_DISABLE  			0x00

#define MAX86916_INT_ALC_OVF_MASK  				(byte)~0b00100000
#define MAX86916_INT_ALC_OVF_ENABLE  			0x20
#define MAX86916_INT_ALC_OVF_DISABLE 			0x00

#define MAX86916_INT_PROX_INT_MASK  			(byte)~0b00010000
#define MAX86916_INT_PROX_INT_ENABLE 			0x10
#define MAX86916_INT_PROX_INT_DISABLE 			0x00

#define MAX86916_SAMPLEAVG_MASK 				(byte)~0b11100000
#define MAX86916_SAMPLEAVG_1  	  				0x00
#define MAX86916_SAMPLEAVG_2  	  				0x20
#define MAX86916_SAMPLEAVG_4  	  				0x40
#define MAX86916_SAMPLEAVG_8 	  				0x60
#define MAX86916_SAMPLEAVG_16  	  				0x80
#define MAX86916_SAMPLEAVG_32 	  				0xA0

#define MAX86916_ROLLOVER_MASK  				0xEF
#define MAX86916_ROLLOVER_ENABLE 				0x10
#define MAX86916_ROLLOVER_DISABLE 				0x00

#define MAX86916_A_FULL_MASK  	  				0xF0

// Mode configuration commands (page 19)
#define MAX86916_SHUTDOWN_MASK  				0x7F
#define MAX86916_SHUTDOWN 		    			0x80
#define MAX86916_WAKEUP  			   			0x00

#define MAX86916_RESET_MASK  		  			0xBF
#define MAX86916_RESET 			    			0x40

#define MAX86916_MODE_MASK  		  			0xFC
#define MAX86916_MODE_DISABLED  				0x00
#define MAX86916_MODE_IRONLY  	 				0x01
#define MAX86916_MODE_REDIRONLY  				0x02
#define MAX86916_MODE_FLEXLED 	  				0x03

// Particle sensing configuration commands (pgs 19-20)
#define MAX86916_ADCRANGE_MASK  				0x9F
#define MAX86916_ADCRANGE_4096 					0x00
#define MAX86916_ADCRANGE_8192 					0x20
#define MAX86916_ADCRANGE_16384 				0x40
#define MAX86916_ADCRANGE_32768  				0x60

#define MAX86916_SAMPLERATE_MASK 				0xE3
#define MAX86916_SAMPLERATE_50 					0x00
#define MAX86916_SAMPLERATE_100  				0x04
#define MAX86916_SAMPLERATE_200 				0x08
#define MAX86916_SAMPLERATE_400  				0x0C
#define MAX86916_SAMPLERATE_800 				0x10
#define MAX86916_SAMPLERATE_1000 				0x14
#define MAX86916_SAMPLERATE_1600 				0x18
#define MAX86916_SAMPLERATE_3200 				0x1C

#define MAX86916_PULSEWIDTH_MASK  				0xFC
#define MAX86916_PULSEWIDTH_70  				0x00
#define MAX86916_PULSEWIDTH_120  				0x01
#define MAX86916_PULSEWIDTH_220  				0x02
#define MAX86916_PULSEWIDTH_420				 	0x03

//LED Range
#define MAX86916_LED1_RGE_MASK 					0xFC
#define MAX86916_LED2_RGE_MASK 					0xF3
#define MAX86916_LED3_RGE_MASK    				0xCF
#define MAX86916_LED4_RGE_MASK   				0x3F
#define MAX86916_LEDx_RGE_X1  	  				0x00
#define MAX86916_LEDx_RGE_X2 	  				0x01
#define MAX86916_LEDx_RGE_X3  	  				0x02
#define MAX86916_LEDx_RGE_X4  	  				0x03

//Multi-LED Mode configuration
#define MAX86916_SLOT1_MASK  		  			0xF0
#define MAX86916_SLOT2_MASK 		  			0x0F
#define MAX86916_SLOT3_MASK 		  			0xF0
#define MAX86916_SLOT4_MASK 		  			0x0F
   
#define SLOT_NONE  				        		0x00
#define SLOT_IR_LED  				      		0x01
#define SLOT_RED_LED 			      			0x02
#define SLOT_GREEN_LED  			    		0x03
#define SLOT_BLUE_LED 			      			0x04
#define SLOT_IR_PILOT 		      				0x05
#define SLOT_RED_PILOT 			    			0x06
#define SLOT_GREEN_PILOT  		    			0x07
#define SLOT_BLUE_PILOT 			    		0x08

#define MAX86916_EXPECTED_PART_ID   				0x2B

#define DEFAULT_RANGE 							0X0
#define DEFAULT_PA 								0x7F
#define STORAGE_SIZE 4 //Each long is 4 bytes so limit this to fit on your micro

