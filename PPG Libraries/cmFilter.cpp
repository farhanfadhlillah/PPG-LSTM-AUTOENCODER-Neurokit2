
#include "cmFilter.h"
#include <cstdio>
#include <cstdlib>

/**

Applies a first-order low-pass filter with a single pole to the input signal using the one-pole recursive filter algorithm.

@param input The input signal to be filtered.

@param filter A pointer to the one-pole recursive low-pass filter struct.

@return The filtered output signal.
*/
double DigitalFilter::pt1FilterApply(double input, lowpassFilter1p *filter)
{
// Calculate the output of the filter using the one-pole recursive filter algorithm
double output = filter->pt1PrevInput + filter->pt1K * (input - filter->pt1PrevInput);

// Update the previous input value to the current output for the next iteration of the filter
filter->pt1PrevInput = output;

// Return the filtered output signal
return output;
}


/**

Applies DC removal filter to the input signal using the given alpha coefficient and previous filtered value.

@param x The input signal to be filtered.

@param prev_w The previous filtered value.

@param alpha The filter coefficient that determines the amount of filtering.

@return A struct containing the filtered value and the intermediate value.
*/
DigitalFilter::dcFilter_t DigitalFilter::dcRemoval(double x, double prev_w, double alpha)
{
// Create a struct to hold the filtered and intermediate values
DigitalFilter::dcFilter_t filtered;

// Calculate the intermediate value
filtered.w = x + alpha * prev_w;

// Calculate the filtered output value
filtered.result = filtered.w - prev_w;

// Return the filtered output and intermediate values in the struct
return filtered;
}

/**

Applies a mean difference filter to the input signal using a sliding window of a specified size.

@param M The input signal to be filtered.

@param filterValues A pointer to the meanDiffFilter_t struct containing the filter parameters.

@return The filtered output signal, which is the difference between the input signal and the moving average of the window.
*/
double DigitalFilter::meanDiffFilter(float M, meanDiffFilter_t *filterValues)
{
double avg = 0;

// Subtract the oldest value in the sliding window from the sum
filterValues->sum -= filterValues->values[filterValues->index];

// Insert the new value at the current index and add it to the sum
filterValues->values[filterValues->index] = M;
filterValues->sum += filterValues->values[filterValues->index];

// Move the index to the next position in the sliding window
filterValues->index++;
filterValues->index = filterValues->index % MEAN_FILTER_SIZE;

// Increase the count of values in the sliding window
if (filterValues->count < MEAN_FILTER_SIZE)
filterValues->count++;

// Calculate the moving average of the window
avg = filterValues->sum / filterValues->count;

// Return the difference between the input signal and the moving average
return avg - M;
}

/**

Applies a fourth-order low-pass filter to the input signal using pre-calculated coefficients.
@param x The input signal to be filtered.
@return The filtered output signal.
*/
double DigitalFilter::lowPass(double x) {
// Shift the input history buffer
xv[0] = xv[1]; xv[1] = xv[2]; xv[2] = xv[3]; xv[3] = xv[4];
// Insert the new input value into the history buffer, scaled by the pre-calculated gain
xv[4] = x / GAIN;
// Shift the output history buffer
yv[0] = yv[1]; yv[1] = yv[2]; yv[2] = yv[3]; yv[3] = yv[4];
// Calculate the new output value using the pre-calculated filter coefficients and history buffer values
yv[4] = (xv[0] + xv[4]) + 4 * (xv[1] + xv[3]) + 6 * xv[2]
+ ( -0.2469881426 * yv[0]) + ( 1.3267482152 * yv[1])
+ ( -2.7499775953 * yv[2]) + ( 2.6278373692 * yv[3]);
// Return the filtered output signal
return yv[4];
}



