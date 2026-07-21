#ifndef CMFILTER_H_
#define CMFILTER_H_

#include <cstdio>
#include <cstdlib>
#define ABS(a)  (a) < 0 ? -(a) : (a)

#define FILTER_INIT_COUNT 255
#define DC_ALPHA 0.8
#define MEAN_FILTER_SIZE 4

#define PI 3.14159265358f

#define MOVEING_WINDOW_SIZE 4
#define HISTOGRAM_SIZE 16

#define THRESHOLD_LEVEL_INIT 300000
#define SIGNAL_LEVEL_INIT 500000
#define NOISE_LEVEL_INIT 100000

#define NO_SIGNAL_LEVEL 250000
#define SIGNAL_RESET_LEVEL 1000000

#define PEACK_DECTION_RESET_COUNT 625



class DigitalFilter {
	
	private:
    // Tambahkan baris-baris ini:
    double xv[5]; // Array untuk input filter (x values)
    double yv[5]; // Array untuk output filter (y values)
    const double GAIN = 1.0; // Konstanta gain filter (sesuaikan jika perlu)
	
	public:
				
		typedef struct DcFilter
		{
		    double w;
		    double result;
		} dcFilter_t;
		
		
		typedef struct LowpassFilter1p
		{
		
		    double pt1K, pt1Dt, pt1RC;
		    double pt1PrevInput;
		
		} lowpassFilter1p;
		
		typedef struct MeanDiffFilte
		{
		    double values[MEAN_FILTER_SIZE];
		    uint8_t index;
		    double sum;
		    uint8_t count;
		} meanDiffFilter_t;
		
		
		dcFilter_t dcFilter;
		lowpassFilter1p lowpassFilter;
		meanDiffFilter_t meanDiff;
		
		uint16_t filter_init_count = 0;
		
		dcFilter_t dcRemoval(double x, double prev_w, double alpha);
		void lowpassFilterInit(float cut, float dt, lowpassFilter1p *filter);
		double pt1FilterApply(double input, lowpassFilter1p *filter);
		double meanDiffFilter(float M, meanDiffFilter_t *filterValues);
		double lowPass(double x); //butterworth low pass filter
		
};



#endif 
