/*
 * This program decompresses JPEG2000 spectral images from the ASPECT spectral
 * imager to raw data.
 *
 * Each spectral band is compressed separately. 
 * 
 * compile on MacOS with
  gcc decompress.c -o decompress \
  -I/usr/local/opt/jasper/include \
  -L/usr/local/opt/jasper/lib \
  -ljasper
 * 
 * Usage: ./decompress WIDTH HEIGHT <input_file.jp2 >raw_file.img
 *
 */

#include <unistd.h>   // for write(), STDIN_FILENO
#include <stdio.h>    // for fprintf(), stderr
#include <stdint.h>   // for uint16_t, etc.
#include <string.h>   // for memset()

#include "jasper/jas_init.h"
#include "jasper/jas_image.h"
#include <jasper/jas_stream.h>


// Replacing ../common.h with hardcoded values
#define MAX_WIDTH       1024
#define MAX_HEIGHT      1024
#define BYTES_PER_PIXEL 2    // 16-bit 

// global static buffer
uint16_t output_img[MAX_HEIGHT*MAX_WIDTH];  // buffer to read the whole raw image, for 16bit 2048x2048 

int main(void) {
  uint16_t x=0, y=0, width=0, height=0;
  uint32_t rawsize=0;
  jas_stream_t *in = NULL;
  jas_image_t *image = NULL;
  int infmt = 0, numcmpts = 0;


  // NOTE: Using jas_init() due to older headers from Homebrew.
  // Upgrade to jas_initialize() once Homebrew ships headers for 4.x
  if (jas_init() != 0) {
    fprintf(stderr, "Cannot init libjasper\n");
    return -1;
  } 

  if (!(in = jas_stream_fdopen(0, "rb"))) {
    fprintf(stderr, "error: cannot open standard input\n");
    return -1;
  }

  if ((infmt = jas_image_getfmt(in)) < 0) {
    fprintf(stderr, "error: input image has unknown format\n");
    return -1;
  }

  if (!(image = jas_image_decode(in, infmt, NULL))) {
    fprintf(stderr, "error: cannot load image data\n");
    return -1;
  }

  numcmpts = jas_image_numcmpts(image);
  width = jas_image_width(image);
  height = jas_image_height(image);
  rawsize = jas_image_rawsize(image);

  fprintf(stderr, "w: %d, h: %d cmpt: %d, raw: %d\n", width, height, numcmpts, rawsize);

  if (numcmpts != 1) {
    fprintf(stderr, "Error: only single-component (grayscale) images are supported.\n");
    return -1;
  }

  if (width > MAX_WIDTH || height > MAX_HEIGHT) {
    fprintf(stderr, "Error: image exceeds max supported dimensions.\n");
    return -1;
  }

  memset(output_img, 0, sizeof(output_img));

  for(y=0; y < height; y++) {
    for(x=0; x < width; x++) {
      int sample = jas_image_readcmptsample(image, 0, x, y);
      output_img[y * width + x] = (uint16_t)sample;
    }
  }

  (void) jas_stream_close(in);
  jas_image_destroy(image);
  jas_cleanup();

  write(1, output_img, width*height*BYTES_PER_PIXEL*numcmpts);

  return 0;
}