#!/usr/bin/env python
# -*- coding: utf-8 -*-

# **********************************************************************************************************************
# File: imageOP.py
# Project: MOOSE Version 0.1.0
# Created: 22.03.2022
# Author: Lalith Kumar Shiyam Sundar
# Email: lalith.shiyamsundar@meduniwien.ac.at
# Institute: Quantitative Imaging and Medical Physics, Medical University of Vienna
# Description: This module contains functions to perform basic image processing operations
# License: Apache 2.0
# **********************************************************************************************************************
import os
import pathlib
import re
import subprocess

import SimpleITK
import numpy as np
import pandas as pd
import pydicom

import constants as c

import cupy as cp
from cucim.skimage.transform import resize

from time import perf_counter


def get_dimensions(nifti_file: str) -> int:
    """
    Get the dimensions of a NIFTI image file
    :param nifti_file: NIFTI file to check
    """
    nifti_img = SimpleITK.ReadImage(nifti_file)
    img_dim = nifti_img.GetDimension()
    return img_dim


def get_pixel_id_type(nifti_file: str) -> str:
    """
    Get the pixel id type of a NIFTI image file
    :param nifti_file: NIFTI file to check
    """
    nifti_img = SimpleITK.ReadImage(nifti_file)
    pixel_id_type = nifti_img.GetPixelIDTypeAsString()
    return pixel_id_type


def get_intensity_statistics(nifti_file: str, multi_label_file: str, out_csv: str) -> None:
    """
    Get the intensity statistics of a NIFTI image file
    :param nifti_file: NIFTI file to check
    :param multi_label_file: Multilabel file that is used to calculate the intensity statistics from nifti_file
    :param out_csv: Path to the output csv file
    :return None
     """
    nifti_img = SimpleITK.ReadImage(nifti_file)
    multi_label_img = SimpleITK.ReadImage(multi_label_file, SimpleITK.sitkInt32)
    intensity_statistics = SimpleITK.LabelIntensityStatisticsImageFilter()
    intensity_statistics.Execute(multi_label_img, nifti_img)
    stats_list = [(intensity_statistics.GetMean(i), intensity_statistics.GetStandardDeviation(i),
                   intensity_statistics.GetMedian(i), intensity_statistics.GetMaximum(i),
                   intensity_statistics.GetMinimum(i)) for i in intensity_statistics.GetLabels()]
    columns = ['Mean', 'Standard-Deviation', 'Median', 'Maximum', 'Minimum']
    stats_df = pd.DataFrame(data=stats_list, index=intensity_statistics.GetLabels(), columns=columns)
    labels_present = stats_df.index.to_list()
    regions_present = []
    for label in labels_present:
        if label in c.ORGAN_INDEX:
            regions_present.append(c.ORGAN_INDEX[label])
        else:
            continue
    stats_df.insert(0, 'Regions-Present', np.array(regions_present))
    stats_df.to_csv(out_csv)


def get_shape_parameters(label_image: str) -> pd.DataFrame:
    """
    Get shape parameters of a label image
    :param label_image: Label image to get the shape parameters from
    :return: shape_parameters_df, a dataframe with the shape parameters (Physical size, Centroid, Elongation, Flatness)
    """
    label_img = SimpleITK.Cast(SimpleITK.ReadImage(label_image), SimpleITK.sitkInt32)
    label_shape_parameters = SimpleITK.LabelShapeStatisticsImageFilter()
    label_shape_parameters.Execute(label_img)
    shape_parameters_list = [(label_shape_parameters.GetPhysicalSize(i), label_shape_parameters.GetCentroid(i),
                              label_shape_parameters.GetElongation(i), label_shape_parameters.GetFlatness(i)) for i
                             in label_shape_parameters.GetLabels()]
    columns = ['Volume(mm3)', 'Centroid', 'Elongation', 'Flatness']
    shape_parameters_df = pd.DataFrame(data=shape_parameters_list, index=label_shape_parameters.GetLabels(),
                                       columns=columns)
    return shape_parameters_df


def get_suv_parameters(dicom_file: str) -> dict:
    """
    Get SUV parameters from dicom tags using pydicom
    :param dicom_file: Path to the Dicom file to get the SUV parameters from
    :return: suv_parameters, a dictionary with the SUV parameters (weight in kg, dose in mBq)
    """
    ds = pydicom.dcmread(dicom_file)
    suv_parameters = {'weight[kg]': ds.PatientWeight, 'total_dose[mBq]': (
            float(ds.RadiopharmaceuticalInformationSequence[0].RadionuclideTotalDose)
            / 1000000
    )}
    return suv_parameters


def convert_bq_to_suv(bq_image: str, out_suv_image: str, suv_parameters: dict) -> str:
    """
    Convert a becquerel PET image to SUV image
    :param bq_image: Path to a becquerel PET image to convert to SUV image (can be NRRD, NIFTI, ANALYZE
    :param out_suv_image: Name of the SUV image to be created (preferrably with a path)
    :param suv_parameters: A dictionary with the SUV parameters (weight in kg, dose in mBq)
    """
    suv_denominator = (suv_parameters["total_dose[mBq]"] / suv_parameters["weight[kg]"]) * 1000  # Units in kBq/mL
    suv_convertor = 1 / suv_denominator
    cmd_to_run = f"c3d {re.escape(bq_image)} -scale {suv_convertor} -o {re.escape(out_suv_image)}"
    subprocess.run(cmd_to_run, shell=True, capture_output=True)
    return out_suv_image


def reslice_identity(reference_image: str, image_to_reslice: str, out_resliced_image: str, interpolation: str) -> None:
    """
    Reslice an image to the same space as another image
    :param reference_image: Path to the reference image to reslice to
    :param image_to_reslice: Path to the image to reslice
    :param out_resliced_image: Path to the resliced image
    :param interpolation: Interpolation method to use (nearest, linear, cubic)

    """
    cmd_to_run = f"c3d {reference_image} {image_to_reslice} -interpolation {interpolation} -reslice-identity -o" \
                 f" {out_resliced_image}"
    subprocess.run(cmd_to_run, shell=True, capture_output=True)


def retain_labels(image_to_retain_labels: str, labels_to_retain: list, out_image: str) -> None:
    """
    Retain only the labels in the list
    :param image_to_retain_labels: Path to the image to retain labels from
    :param labels_to_retain: List of labels to retain
    :param out_image: Path to the retained image
    """
    labels = " ".join(str(i) for i in labels_to_retain)
    cmd_to_run = f"c3d {re.escape(image_to_retain_labels)} -retain-labels {labels} -o {re.escape(out_image)}"
    subprocess.run(cmd_to_run, shell=True, capture_output=True)


def shift_intensity(image_to_shift: str, shift_amount: int, out_image: str) -> None:
    """
    Shift the intensity of an image
    :param image_to_shift: Path to the image to shift
    :param shift_amount: Amount to shift the image by
    :param out_image: Path to the shifted image
    """
    cmd_to_run = f"c3d {re.escape(image_to_shift)} -shift {str(shift_amount)} -o {re.escape(out_image)}"
    subprocess.run(cmd_to_run, shell=True, capture_output=True)


def replace_intensity(image_to_replace: str, intensity: list, out_image: str) -> None:
    """
    Replace the intensity of an image
    :param image_to_replace: Path to the image to replace
    :param intensity:
    Replace intensity I1 by J1, I2 by J2 and so on. Allowed values of intensity include nan, inf and -inf.
    :param out_image: Path to the replaced image
    """
    replace_intensity_str = " ".join(str(i) for i in intensity)
    cmd_to_run = f"c3d {re.escape(image_to_replace)} -replace {replace_intensity_str} -o {re.escape(out_image)}"
    subprocess.run(cmd_to_run, shell=True, capture_output=True)


def binarize(label_img: str, out_img: str) -> None:
    """
    Binarize an image
    :param label_img: Path to the image to binarize
    :param out_img: Path to the binarized image
    """
    cmd_to_run = f"c3d {re.escape(label_img)} -binarize -o {re.escape(out_img)}"
    subprocess.run(cmd_to_run, shell=True, capture_output=True)


def remove_overlays(reference_image: str, image_to_remove_overlays: str, out_image: str) -> None:
    """
    Remove overlays from an image
    :param reference_image: Path to the reference image
    :param image_to_remove_overlays: Path to the image to remove overlays from
    :param out_image: Path to the image with overlays removed
    """
    cmd_to_run = f"c3d {re.escape(reference_image)} -binarize -popas BIN -push BIN -replace 1 0 0 1 -popas INVBIN " \
                 f"-push INVBIN {re.escape(image_to_remove_overlays)} -multiply -o {re.escape(out_image)}"
    subprocess.run(cmd_to_run, shell=True, capture_output=True)


def sum_image_stack(img_dir: str, wild_card: str, out_img: str) -> None:
    """
    Sum a list of images
    :param img_dir: Directory containing the list of images to sum
    :param wild_card: Wildcard to use to find the images to sum
    :param out_img: Path to the summed image
    """
    os.chdir(img_dir)
    cmd_to_run = f"c3d {wild_card} -accum -add -endaccum -o {re.escape(out_img)}"
    subprocess.run(cmd_to_run, shell=True, capture_output=True)


def add_image(image_to_add: str, image_to_add_to: str, out_image: str) -> None:
    """
    Add two images together
    :param image_to_add: Path to the image to add
    :param image_to_add_to: Path to the image to add to
    :param out_image: Path to the added image
    """
    cmd_to_run = f"c3d {re.escape(image_to_add)} {re.escape(image_to_add_to)} -add -o {re.escape(out_image)}"
    subprocess.run(cmd_to_run, shell=True, capture_output=True)


def crop_image_using_mask(image_to_crop: str, multilabel_mask: str, out_image: str, label_intensity=int) -> str:
    """
    Crop an image using a mask
    :param image_to_crop: Path to the image to crop
    :param multilabel_mask: Path to the multilabel mask
    :param out_image: Path to the cropped image
    :param label_intensity: Label intensity to crop
    """
    img = SimpleITK.ReadImage(image_to_crop)
    mask = SimpleITK.ReadImage(multilabel_mask)
    label_shape_filter = SimpleITK.LabelShapeStatisticsImageFilter()
    label_shape_filter.Execute(mask == label_intensity)
    bbox = np.asarray(label_shape_filter.GetBoundingBox(1))
    img_dim = np.asarray(img.GetSize())
    start_index = bbox[0:3]
    size = bbox[3:]
    new_index = start_index - c.CROPPED_PADDING
    new_size = size + c.CROPPED_PADDING
    lower_bounds = new_index <= 0
    new_index[lower_bounds] = start_index[lower_bounds]
    upper_bounds = new_index + new_size
    out_of_bounds = upper_bounds >= img_dim
    padding_value = img_dim[out_of_bounds] - (new_index[out_of_bounds] + size[out_of_bounds])
    new_size[out_of_bounds] = size[out_of_bounds] + padding_value
    cropped_img = SimpleITK.RegionOfInterest(img, new_size.astype("int").tolist(), (new_index.astype("int").tolist()))
    SimpleITK.WriteImage(cropped_img, out_image)
    return out_image


def split_mask_to_left_right(binary_mask_path: str, out_dir: str) -> None:
    """
    Split a binary mask into left and right masks
    :param binary_mask_path: Path to the binary mask
    :param out_dir: Path to the output directory
    """
    binary_mask = pathlib.Path(binary_mask_path).stem.split(".")[0]
    right_mask = 'R-' + binary_mask + '.nii.gz'
    left_mask = 'L-' + binary_mask + '.nii.gz'
    cmd_to_run = f"c3d {re.escape(binary_mask_path)} -as SEG -cmv -pop -pop  -thresh 50% inf 1 0 -as MASK -push SEG " \
                 f"-times -o {re.escape(os.path.join(out_dir, left_mask))} -push MASK -replace 1 0 0 1 -push SEG " \
                 f"-times -o {re.escape(os.path.join(out_dir, right_mask))}"
    subprocess.run(cmd_to_run, shell=True, capture_output=True)


def scale_mask(mask_path: str, out_path: str, scale_factor: int) -> None:
    """
    Scale a mask with a particular scaling factor
    :param mask_path: Path to the mask to scale
    :param out_path: Path to the scaled mask
    :param scale_factor: Scale factor
    """
    cmd_to_run = f"c3d {re.escape(mask_path)} -scale {scale_factor} -o {re.escape(out_path)}"
    subprocess.run(cmd_to_run, shell=True, capture_output=True)


def extract_central_slice_as_png(image_path: str, out_path: str) -> str:
    """
    Extract the central slice of an image as a png
    :param image_path: Path to the image
    :param out_path: Path to the output png
    :return: Path to the output png
    """
    cmd_to_run = f"c3d {re.escape(image_path)} -slice y 50% -flip y -type uchar -stretch 0.001% 99.999% 5 255 -o " \
                 f"{re.escape(out_path)} "
    subprocess.run(cmd_to_run, shell=True, capture_output=True)
    return out_path


def get_resize_factor(img: np.ndarray, spacing: list, target_spacing: list) -> np.ndarray:
    """
    Get the resize factor of an image. The resize factor determines the new size of an image
    with a certain spacing. The resize factor is the ratio of the current spacing and the target spacing.

    :param img: Input image. Can be n-dimensional.
    :type img: np.ndarray
    :param spacing: Spacing of the input image.
    :type spacing: list
    :param target_spacing: Target spacing.
    :type target_spacing: list
    :return: Resize factor
    :rtype: np.ndarray
    """
    # As npy arrays
    old_spacing = np.asarray(spacing)
    new_spacing = np.asarray(target_spacing)

    # Calculate resize factor
    resize_factor = old_spacing/new_spacing

    # Calculate new shape
    new_shape = img.shape * resize_factor

    # Round, because new_shape could be not an integer
    new_shape = np.round(new_shape)

    # Based on rounded new_shape, recalculate the resize_factor for this
    # particular rounded shape
    resize_factor = new_shape / img.shape

    return resize_factor


def resample_image(nifti_file: str, target_spacing: list, order: int) -> SimpleITK.Image:
    """Resample image to the target spacing

    :param nifti_file: NIFTI filepath
    :type nifti_file: str
    :param target_spacing: Target spacing (the new spacing I want, can be either int or float)
    :type target_spacing: list
    :param order: Order of spline interpolation (0: Nearest-neighbor, 3: Bi-cubic). Use 0 for binary segmentation mask and 3 for images.
    :type order: int
    :return: SimpleITK image.
    :rtype: SimpleITK.Image
    """
    # Start counter
    start_time = perf_counter()

    # Read sitk image
    sitk_img = SimpleITK.ReadImage(nifti_file)
    # Get npy array
    img = SimpleITK.GetArrayFromImage(sitk_img)
    # Transpose: (z, x, y) -> (x, y, z)
    img = np.transpose(img)
    # Get spacing of input image
    spacing = sitk_img.GetSpacing()
    # Get resize factor
    resize_factor = get_resize_factor(img, spacing, target_spacing)
    # Calculate target shape
    new_shape = resize_factor * img.shape
    new_shape = [int(x) for x in new_shape]

    # Print statements
    print(nifti_file)
    print(f"spacing: {spacing}")
    print(f"shape: {img.shape}")
    print(f"new spacing: {target_spacing}")
    print(f"new shape: {new_shape}")

    # Create cupy array
    img = cp.asarray(img)

    # Resize image
    resampled_img = resize(img, output_shape=new_shape, order=order, mode="edge", anti_aliasing=False)

    # Get back npy array
    resampled_img = cp.asnumpy(resampled_img)  # Alternative: img_arr = cp.float32(resampled_img.get())

    # --------------------------
    # Convert back to sitk image
    # --------------------------
    # Transpose back (x, y, z) -> (z, x, y)
    resampled_img = np.transpose(resampled_img)
    # Create sitk image
    sitk_out = SimpleITK.GetImageFromArray(resampled_img)
    # Copy sitk metadata
    sitk_out.SetOrigin(sitk_img.GetOrigin())
    sitk_out.SetDirection(sitk_img.GetDirection())
    sitk_out.SetSpacing(target_spacing)

    # End counter
    end_time = perf_counter()
    # Report resampling time
    delta_time = end_time - start_time
    print(f"Resampling took {delta_time:.2f} seconds")

    return sitk_out