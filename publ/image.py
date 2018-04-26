# image.py
''' Managing image renditions '''

from __future__ import absolute_import, with_statement

import os
import math
import hashlib
import logging

import PIL.Image

from . import config
from . import model, utils

logger = logging.getLogger(__name__)  # pylint: disable=invalid-name


def round(num):
    """ Round a number to the nearest integer """
    return int(num + 0.5)


class Image:
    """ The basic Image class, which knows about the base version and how to
    generate renditions from it """

    def __init__(self, record):
        """ Get the base image from an index record """
        self._record = record

    def get_rendition(self, output_scale, kwargs):
        """
        Get the rendition for this image, generating it if necessary.
        Returns a tuple of `(relative_path, width, height)`, where relative_path
        is relative to the static file directory (i.e. what one would pass into
        `get_static()`)

        output_scale -- the upsample factor for the requested rendition

        Keyword arguments:

        scale -- the downsample factor for the base rendition
        scale_min_width -- the minimum width after downsampling
        scale_min_height -- the minimum height after downsampling
        width -- the width to target
        height -- the height to target
        max_width -- the maximum width
        max_height -- the maximum height
        resize -- how to fit the width and height; "fit", "fill", or "stretch"
        fill_crop_x -- horizontal offset fraction for resize="fill"
        fill_crop_y -- vertical offset fraction for resize="fill"
        format -- output format
        background -- background color when converting transparent to opaque
        quality -- the JPEG quality to save the image as
        """

        input_filename = self._record.file_path
        basename, ext = os.path.splitext(os.path.basename(input_filename))
        basename = utils.make_slug(basename)

        flatten = None
        if kwargs.get('format'):
            ext = '.' + kwargs['format']
            flatten = ext not in ['.png', '.gif']

        # The spec for building the output filename
        out_spec = [basename, self._record.checksum[-10:]]

        out_args = {}

        size, box = self.get_rendition_size(kwargs, output_scale)
        if size and (size[0] < self._record.width or size[1] < self._record.height):
            out_spec.append('x'.join([str(v) for v in size]))
        if box:
            out_spec.append('-'.join([str(v) for v in box]))

        if flatten and 'background' in kwargs:
            bg_color = kwargs['background']
            if isinstance(bg_color, (tuple, list)):
                out_spec.append('b' + '-'.join([str(a) for a in bg_color]))
            else:
                out_spec.append('b' + str(bg_color))

        if (ext == '.jpg' or ext == '.jpeg') and 'quality' in kwargs:
            quality = kwargs['quality']
            if quality:
                out_spec.append('q' + str(quality))
            out_args['quality'] = quality

        # Build the output filename
        out_basename = '_'.join([str(s) for s in out_spec]) + ext
        out_rel_path = os.path.join(
            config.image_output_subdir,
            self._record.checksum[0:2],
            self._record.checksum[2:6],
            out_basename)
        out_fullpath = os.path.join(config.static_folder, out_rel_path)
        out_dir = os.path.dirname(out_fullpath)

        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)

        if not os.path.isfile(out_fullpath):
            # Process the file
            input_image = PIL.Image.open(input_filename)
            if size:
                input_image = input_image.resize(size=size,
                                                 box=box,
                                                 resample=PIL.Image.LANCZOS)
            if input_image.mode == 'RGBA' and flatten:
                input_image = self.flatten(input_image, kwargs)
            input_image.save(out_fullpath, optimize=True, **out_args)

        return out_rel_path, size

    def get_rendition_size(self, spec, output_scale):
        mode = spec.get('resize', 'fit')

        if mode == 'fit':
            return self.get_rendition_fit_size(spec, output_scale)

        if mode == 'fill':
            return self.get_rendition_fill_size(spec, output_scale)

        if mode == 'stretch':
            return self.get_rendition_stretch_size(spec, output_scale)

        raise ValueError("Unknown resize mode {}".format(mode))

    def get_rendition_fit_size(self, spec, output_scale):
        """ Determine the scaled size based on the provided spec """

        iw = self._record.width  # input width
        ih = self._record.height  # input height

        width = iw
        height = ih

        scale = spec.get('scale')
        if scale:
            width = width / scale
            height = height / scale

        min_width = spec.get('scale_min_width')
        if min_width and width < min_width:
            height = height * min_width / width
            width = min_width

        min_height = spec.get('scale_min_height')
        if min_height and height < min_height:
            width = width * min_height / height
            height = min_height

        tgt_width, tgt_height = spec.get('width'), spec.get('height')

        if tgt_width and width > tgt_width:
            height = height * tgt_width / width
            width = tgt_width

        tgt_height = spec.get('height')
        if tgt_height and height > tgt_height:
            width = width * tgt_height / height
            height = tgt_height

        tgt_width, tgt_height = spec.get('max_width'), spec.get('max_height')

        if tgt_width and width > tgt_width:
            height = height * tgt_width / width
            width = tgt_width

        tgt_height = spec.get('height')
        if tgt_height and height > tgt_height:
            width = width * tgt_height / height
            height = tgt_height

        width = width * output_scale
        height = height * output_scale

        # Never scale to larger than the base rendition
        width = min(round(width), iw)
        height = min(round(height), ih)

        return (width, height), None

    def get_rendition_fill_size(self, spec, output_scale):
        """ Determine the scale-crop size given the provided spec """

        iw = self._record.width
        ih = self._record.height

        width = iw
        height = ih

        scale = spec.get('scale')
        if scale:
            width = width / scale
            height = height / scale

        min_width = spec.get('scale_min_width')
        if min_width and width < min_width:
            width = min_width

        min_height = spec.get('scale_min_height')
        if min_height and height < min_height:
            height = min_height

        tgt_width, tgt_height = spec.get('width'), spec.get('height')

        if tgt_width and width > tgt_width:
            width = tgt_width

        tgt_height = spec.get('height')
        if tgt_height and height > tgt_height:
            height = tgt_height

        tgt_width, tgt_height = spec.get('max_width'), spec.get('max_height')

        if tgt_width and width > tgt_width:
            width = tgt_width

        tgt_height = spec.get('height')
        if tgt_height and height > tgt_height:
            height = tgt_height

        width = width * output_scale
        height = height * output_scale

        # Never scale to larger than the base rendition (but keep the output
        # aspect)
        if width > iw:
            height = height * iw / width
            width = iw

        if height > ih:
            width = width * ih / height
            height = ih

        # Determine the box size
        box_w = min(iw, round(width * ih / height))
        box_h = min(ih, round(height * iw / width))

        # Box offset
        box_x = round((iw - box_w) * spec.get('fill_crop_x', 0.5))
        box_y = round((ih - box_h) * spec.get('fill_crop_y', 0.5))

        return (round(width), round(height)), (box_x, box_y, box_x + box_w, box_y + box_h)

    def get_rendition_stretch_size(self, spec, output_scale):
        """ Determine the scale-crop size given the provided spec """

        width = self._record.width
        height = self._record.height

        scale = spec.get('scale')
        if scale:
            width = width / scale
            height = height / scale

        min_width = spec.get('scale_min_width')
        if min_width and width < min_width:
            width = min_width

        min_height = spec.get('scale_min_height')
        if min_height and height < min_height:
            height = min_height

        tgt_width, tgt_height = spec.get('width'), spec.get('height')

        if tgt_width and width > tgt_width:
            width = tgt_width

        tgt_height = spec.get('height')
        if tgt_height and height > tgt_height:
            height = tgt_height

        tgt_width, tgt_height = spec.get('max_width'), spec.get('max_height')

        if tgt_width and width > tgt_width:
            width = tgt_width

        tgt_height = spec.get('height')
        if tgt_height and height > tgt_height:
            height = tgt_height

        width = width * output_scale
        height = height * output_scale

        return (round(width), round(height)), None

    @staticmethod
    def flatten(image, kwargs):
        if 'background' in kwargs:
            background = PIL.Image.new('RGB', image.size, kwargs['background'])
            background.paste(image, mask=image.split()[3])
            return background

        return image.convert('RGB')


def get_image(path, search_path):
    """ Get an Image object. Arguments:

    path -- the image's filename
    search_path -- a search path or list of search paths
    """

    file_path = utils.find_file(path, search_path)
    if not file_path:
        return None

    record = model.Image.get_or_none(file_path=file_path)
    mtime = os.stat(file_path).st_mtime
    if not record or record.mtime < mtime:
        # Reindex the file
        logger.info("Updating image %s", file_path)

        # compute the md5sum; from https://stackoverflow.com/a/3431838/318857
        md5 = hashlib.md5()
        with open(file_path, 'rb') as file:
            for chunk in iter(lambda: file.read(16384), b""):
                md5.update(chunk)

        image = PIL.Image.open(file_path)
        values = {
            'checksum': md5.hexdigest(),
            'width': image.width,
            'height': image.height,
            'mtime': mtime
        }
        record, created = model.Image.get_or_create(
            file_path=file_path, defaults=values)
        if not created:
            record.update(**values).where(model.Image.id == record.id)

    return Image(record)
