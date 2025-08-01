"""
Authors: Lawrence Schobs, lawrenceschobs@gmail.com

Module from the implementation of L. A. Schobs, A. J. Swift and H. Lu, "Uncertainty Estimation for Heatmap-Based Landmark Localization,"
in IEEE Transactions on Medical Imaging, vol. 42, no. 4, pp. 1021-1034, April 2023, doi: 10.1109/TMI.2022.3222730.

Functions related to interpreting the uncertainty quantiles from the quantile binning method in terms of:
   A) Correlation of uncertainty with error (fit_line_with_ci)
   B) Perform Isotonic regression on uncertainty & error pairs (quantile_binning_and_est_errors)
   C) Plot boxplots: generic_box_plot_loop, format_plot, box_plot_per_model, box_plot_comparing_q
   D) Plot cumularive error plots: plot_cumulative
   E) Big caller functions for analysis loop for QBinning:  generate_fig_individual_bin_comparison, generate_fig_comparing_bins

"""
import logging
import math
import os
from typing import Any, Dict, List, Optional, Tuple, Union

import matplotlib.lines as mlines
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
from matplotlib.ticker import ScalarFormatter
from sklearn.isotonic import IsotonicRegression

from kale.evaluate.similarity_metrics import evaluate_correlations
from kale.evaluate.uncertainty_metrics import evaluate_bounds, evaluate_jaccard, get_mean_errors
from kale.prepdata.tabular_transform import generate_struct_for_qbin
from kale.utils.save_xlsx import generate_summary_df


def quantile_binning_and_est_errors(
    errors: List[float],
    uncertainties: List[float],
    num_bins: int,
    type: str = "quantile",
    acceptable_thresh: float = 5,
    combine_middle_bins: bool = False,
) -> Tuple[List[List[float]], List[float]]:
    """
    Calculate quantile thresholds, and isotonically regress errors and uncertainties
    and get estimated error bounds.

    Args:
        errors (List[float]): List of errors.
        uncertainties (List[float]): List of uncertainties.
        num_bins (int): Number of quantile bins.
        type (str, optional): Type of thresholds to calculate, "quantile" recommended.
                              Defaults to "quantile".
        acceptable_thresh (float, optional): Acceptable error threshold. Only relevant
                                             if type="error-wise". Defaults to 5.
        combine_middle_bins (bool, optional): Whether to combine middle bins.
                                              Defaults to False.

    Returns:
        Tuple[List[List[float]], List[float]]: List of quantile thresholds and
                                               estimated error bounds.
    """

    if len(errors) != len(uncertainties):
        raise ValueError(
            "Length of errors and uncertainties must be the same. errors is length %s and uncertainties is length %s"
            % (len(errors), len(uncertainties))
        )

    valid_types = {"quantile", "error-wise"}
    if type not in valid_types:
        raise ValueError("results: type must be one of %r. " % valid_types)

    # Isotonically regress line
    ir = IsotonicRegression(out_of_bounds="clip", increasing=True)

    _ = ir.fit_transform(uncertainties, errors)

    uncert_boundaries = []
    estimated_errors = []

    # Estimate error bounds for each quantile bin
    if type == "quantile":
        quantiles = np.arange(1 / num_bins, 1, 1 / num_bins)[: num_bins - 1]
        for q in range(len(quantiles)):
            q_conf_higher = [np.quantile(uncertainties, quantiles[q])]
            q_error_higher = ir.predict(q_conf_higher)

            estimated_errors.append(q_error_higher[0])
            uncert_boundaries.append(q_conf_higher)

    elif type == "error_wise":
        quantiles = np.arange(num_bins - 1)
        estimated_errors = [[(acceptable_thresh * x)] for x in quantiles]

        uncert_boundaries = [(ir.predict(x)).tolist() for x in estimated_errors]
        raise NotImplementedError("error_wise Quantile Binning not implemented yet")

    # IF combine bins, we grab only the values for the two outer bins
    if combine_middle_bins:
        estimated_errors = [estimated_errors[0], estimated_errors[-1]]
        uncert_boundaries = [uncert_boundaries[0], uncert_boundaries[-1]]

    return uncert_boundaries, estimated_errors

class BoxplotStyleConfig:  
    # Plot style  
    matplotlib_style: str = "fivethirtyeight"  
    hatch_type: str = "o"  
      
    # Colors and styling  
    box_edge_color: str = "black"  
    box_linewidth: float = 1.0  
    median_color: str = "crimson"  
    median_linewidth: float = 3.0  
    mean_facecolor: str = "crimson"  
    mean_edgecolor: str = "black"  
    mean_markersize: float = 10.0  
      
    # Individual dots  
    dot_alpha_normal: float = 0.75  
    dot_alpha_alt: float = 0.2  
      
    # Spacing values  
    inner_spacing: float = 0.1  
    middle_spacing: float = 0.02  
    gap_large: float = 0.25  
    gap_small: float = 0.12  
    outer_gap_small: float = 0.35  
    outer_gap_large: float = 0.24  
    comparing_q_spacing: float = 0.2  
      
    # Box widths  
    default_box_width: float = 0.25  
    comparing_q_width_base: float = 0.2  
      
    # Font sizes  
    sample_info_fontsize: int = 25  
    legend_fontsize: int = 20  
      
    # Layout  
    legend_columnspacing: float = 2.0  
    legend_bbox_anchor: Tuple[float, float] = (0.5, 1.18)  
    subplot_bottom: float = 0.15  
    subplot_left: float = 0.15  
      
    # Figure saving  
    figure_size: Tuple[float, float] = (16.0, 10.0)  
    dpi: int = 600  
    bbox_inches: str = "tight"  
    pad_inches: float = 0.1

class Box_plot:
    def __init__(self, style_config: Optional[BoxplotStyleConfig] = None):  
        self.config = style_config or BoxplotStyleConfig()  
        self.ax = None  
        self.circ_patches = []  
        self.max_bin_height = 0.0  
        self.all_sample_label_x_locs = []  
        self.all_sample_percs = []  
          
    def _setup_plot(self):  
        """Initialize plot with common settings"""  
        plt.style.use(self.config.matplotlib_style)  
        self.ax = plt.gca()  
        self.ax.xaxis.grid(False)
          
    def _create_boxplot_with_styling(self, displayed_data, x_loc, width, cmaps, i, hash_idx, custom_hatch=None, custom_color=None):  
        """Create and style individual boxplot"""  
        face_color = custom_color if custom_color else cmaps[i]  
        apply_hatch = custom_hatch if custom_hatch else self.config.hatch_type

        rect = self.ax.boxplot(  
            displayed_data, positions=x_loc, sym="", widths=width,   
            showmeans=True, patch_artist=True  
        )  
          
        # Apply styling using config  
        for r in rect["boxes"]:  
            r.set(color=self.config.box_edge_color, linewidth=self.config.box_linewidth)  
            r.set(facecolor=face_color)  
            if hash_idx == 1:  
                r.set_hatch(apply_hatch)  
                  
        for median in rect["medians"]:  
            median.set(color=self.config.median_color, linewidth=self.config.median_linewidth)  
              
        for mean in rect["means"]:  
            mean.set(markerfacecolor=self.config.mean_facecolor,   
                    markeredgecolor=self.config.mean_edgecolor,   
                    markersize=self.config.mean_markersize)  
          
        return rect  
          
    def _add_individual_dots(self, displayed_data, x_loc, cmaps, uncertainty_types_list,alpha=None, custom_color=None):  
        """Add individual data points with jitter"""  
        alp = alpha if alpha is not None else self.config.dot_alpha_normal
        col = custom_color if custom_color else cmaps[len(uncertainty_types_list)]
        x = np.random.normal(x_loc, 0.01, size=len(displayed_data))  
        self.ax.plot(  
            x, displayed_data,  
            color=col,  
            marker=".", linestyle="None",  
            alpha=alp  
        )  
          
    def _create_legend_patch(self, cmaps, i, model_type, uncertainty_type, hash_idx):  
        """Create legend patches for models and uncertainty types"""  
        if hash_idx == 1:  
            patch = patches.Patch(  
                facecolor=cmaps[i],  
                label=model_type + " " + uncertainty_type,  
                hatch=self.config.hatch_type,  
                edgecolor=self.config.box_edge_color  
            )  
        else:  
            patch = patches.Patch(  
                facecolor=cmaps[i],   
                label=model_type + " " + uncertainty_type  
            )  
        return patch  
          
    def _calculate_spacing(self, num_bins, list_comp_bool, current_spacing):  
        """Calculate spacing between plots based on number of bins"""  
        if list_comp_bool:  
            if num_bins > 9:  
                return current_spacing + self.config.gap_large  
            else:  
                return current_spacing + self.config.gap_small  
        else:  
            if num_bins > 10:  
                return current_spacing + self.config.outer_gap_small  
            else:  
                return current_spacing + self.config.gap_large 
             
    def _handle_sample_info(self, show_sample_info, model_data, all_b_data, rect, average_samples_per_bin):  
        """Handle sample information calculation and positioning"""  
        if show_sample_info != "None":  
            flattened_model_data = [x for xss in model_data for x in xss]  
            percent_size = np.round(len(all_b_data) / len(flattened_model_data) * 100, 1)  
            average_samples_per_bin.append(percent_size)  
            
            if show_sample_info == "All":  
                (x_l, y), (x_r, _) = rect["caps"][-1].get_xydata()  
                x_line_center = (x_l + x_r) / 2  
                self.all_sample_label_x_locs.append(x_line_center)  
                self.all_sample_percs.append(percent_size)    

    def handle_average_info(self, show_sample_info, inbetween_locs, average_samples_per_bin):
        """Keep track of average sample statistics. Plot at the END so we know what the max height for all Qs are."""
        if show_sample_info == "Average":  
            middle_x = np.mean(inbetween_locs)  
            mean_perc = np.round(np.mean(average_samples_per_bin), 1)  
            std_perc = np.round(np.std(average_samples_per_bin), 1)  
            self.all_sample_label_x_locs.append(middle_x)  
            self.all_sample_percs.append([mean_perc, std_perc])

    def _format_plot(self, save_path: Optional[str], show_sample_info: str, to_log: bool,  
                y_lim: float, y_lim_min: float, convert_to_percent: bool,  
                x_label: str, y_label: str, font_size_1: int, font_size_2: int,  
                bin_label_locs: List[float], x_axis_labels: List[str],  
                num_bins: int, uncertainty_types_list: List[List[str]],  
                comparing_q: bool = False) -> None:
        """
        This function takes a matplotlib Axes object and formats the plot according to the provided parameters.

        Args:
            ax: A matplotlib axes object to be formatted.
            save_path: The path where the plot should be saved. If None, the plot will be shown using plt.show().
            show_sample_info: Determines how sample information is displayed. Can be "None", "Average", or "All".
            to_log: If True, sets the y-axis to log scale.
            circ_patches: List of matplotlib patches to be added to the legend.
            y_lim: The upper limit for the y-axis.
            y_lim_min: The lower limit for the y-axis.
            convert_to_percent: If True, converts y-axis values to percentages.
            x_label: The label for the x-axis.
            y_label: The label for the y-axis.
            font_size_1: The font size for the axis labels.
            font_size_2: The font size for the tick labels.
            bin_label_locs: The x-axis locations of the bin labels.
            x_axis_labels: The labels for the x-axis.
            num_bins: The number of bins.
            uncertainty_types_list: The list of uncertainty types.
            all_sample_percs: The percentage of samples for each bin.
            all_sample_label_x_locs: The x-axis locations of the sample percentage labels.
            max_bin_height: The maximum height of a bin in the plot.
            comparing_q: If True, it uses a ticker.FixedFormatter for the x-axis.

        Returns:
            None
        """

        # Show the average samples on top of boxplots, aligned. if lots of bins we can lower the height.
        if show_sample_info != "None":  
            for idx_text, perc_info in enumerate(self.all_sample_percs):  
                if show_sample_info == "Average":  
                    self.ax.text(  
                        self.all_sample_label_x_locs[idx_text],  
                        self.max_bin_height * 0.8,  # Position
                        r"$\bf{PSB}$" + ": \n" + r"${} \pm$".format(perc_info[0]) + "\n" + r"${}$".format(perc_info[1]),  
                        verticalalignment="bottom",  # Centered bottom with line
                        horizontalalignment="center",  
                        fontsize=self.config.sample_info_fontsize,   
                    )  
                elif show_sample_info == "All":  
                    label_height = self.max_bin_height + (3 if idx_text % 2 == 0 else 1)  
                    self.ax.text(  
                        self.all_sample_label_x_locs[idx_text][0],  
                        label_height,  
                        r"$\bf{PSB}$" + ": \n" + str(perc_info) + "%",  
                        verticalalignment="bottom",  
                        horizontalalignment="center",  
                        fontsize=self.config.sample_info_fontsize,  
                    )  
    
        self.ax.set_xlabel(x_label, fontsize=font_size_1)  
        self.ax.set_ylabel(y_label, fontsize=font_size_1)  
        self.ax.set_xticks(bin_label_locs)  
     
        plt.subplots_adjust(bottom=self.config.subplot_bottom)   
        plt.subplots_adjust(left=self.config.subplot_left)      
    
        plt.xticks(fontsize=font_size_2)  
        plt.yticks(fontsize=font_size_2)  
    
        # X-axis formatting logic remains the same  
        if comparing_q:  
            self.ax.xaxis.set_major_formatter(ticker.FixedFormatter(x_axis_labels))  
        else:  
            if num_bins <= 5:  
                self.ax.xaxis.set_major_formatter(ticker.FixedFormatter(x_axis_labels[:-1] * (len(uncertainty_types_list) * 2)))  
            elif num_bins < 15:  
                number_blanks_0 = ["" for x in range(math.floor((num_bins - 3) / 2))]  
                number_blanks_1 = ["" for x in range(num_bins - 3 - len(number_blanks_0))]  
                new_labels = (  
                    [x_axis_labels[0]] + number_blanks_0 + [r"$\rightarrow$"] + number_blanks_1 + [x_axis_labels[-1]]  
                )  
                self.ax.xaxis.set_major_formatter(ticker.FixedFormatter(new_labels * (len(uncertainty_types_list) * 2)))  
            else:  
                number_blanks_0 = ["" for x in range(math.floor((num_bins - 5) / 2))]  
                number_blanks_1 = ["" for x in range(num_bins - 5 - len(number_blanks_0))]  
                new_labels = (  
                    [""] + [x_axis_labels[0]] + number_blanks_0 + [r"$\rightarrow$"] +   
                    number_blanks_1 + [x_axis_labels[-1]] + [""]  
                )  
                self.ax.xaxis.set_major_formatter(ticker.FixedFormatter(new_labels * (len(uncertainty_types_list) * 2)))  
    
        if to_log:  
            self.ax.set_yscale("symlog", base=2)  
            self.ax.yaxis.set_major_formatter(ScalarFormatter())  
            self.ax.set_ylim(y_lim_min, y_lim)  
        else:  
            self.ax.set_ylim((y_lim_min, y_lim))  
    
        if convert_to_percent and y_lim > 100:  
            plt.yticks(np.arange(0, y_lim, 20))  
    
        # Replace hardcoded legend values  
        red_triangle_mean = mlines.Line2D(  
            [], [], color=self.config.median_color, marker="^",   
            markeredgecolor=self.config.box_edge_color, linestyle="None",   
            markersize=self.config.mean_markersize, label="Mean"  
        )  
        self.circ_patches.append(red_triangle_mean)  
    
        red_line_median = mlines.Line2D(  
            [], [], color=self.config.median_color, marker="",   
            markeredgecolor=self.config.box_edge_color,   
            markersize=self.config.mean_markersize, label="Median"  
        )  
        self.circ_patches.append(red_line_median)  
    
        if show_sample_info == "Average":  
            self.circ_patches.append(patches.Patch(color="none", label=r"$\bf{PSB}$" + r": % Samples per Bin"))  
    
        num_cols_legend = math.ceil(len(self.circ_patches) / 2)  
        self.ax.legend(  
            handles=self.circ_patches,  
            fontsize=self.config.legend_fontsize,          
            ncol=num_cols_legend,  
            columnspacing=self.config.legend_columnspacing,  
            loc="upper center",  
            bbox_to_anchor=self.config.legend_bbox_anchor,     
            fancybox=True,  
            shadow=False,  
        )  
    
        if save_path is not None:  
            plt.gcf().set_size_inches(*self.config.figure_size)    
            plt.tight_layout()  
            plt.savefig(save_path, dpi=self.config.dpi,            
                    bbox_inches=self.config.bbox_inches,        
                    pad_inches=self.config.pad_inches)        
            plt.close()  
        else:  
            plt.gcf().set_size_inches(*self.config.figure_size)    
            plt.show()  
            plt.close()


    def generic_box_plot_loop(
        self,
        cmaps: List[str],
        target_uncert_dicts: Dict[str, List[List[float]]],
        uncertainty_types_list: List[List[str]],
        models: List[str],
        x_axis_labels: List[str],
        x_label: str,
        y_label: str,
        num_bins: int,
        list_comp_bool: bool,
        width: float,
        y_lim_min: float,
        font_size_1: int,
        font_size_2: int,
        show_sample_info: str = "None",
        save_path: Optional[str] = None,
        y_lim: int = 120,
        convert_to_percent: bool = True,
        to_log: bool = False,
        show_individual_dots: bool = True,
    ) -> None:
        """
        This function generates box plots for multiple types of data coming from various models. It is highly customizable
        and can handle different specifications for plot attributes.

        Customizations include:

        1. Color specification: User can provide a list of color specifications for each box plot using `cmaps` parameter.
        2. Axis labels: The x and y axis labels can be customized using `x_label` and `y_label` parameters.
        3. Box width: The width of each box plot can be adjusted using `width` parameter.
        4. Font sizes: Two different font sizes can be used in the plot, adjustable by `font_size_1` and `font_size_2`.
        5. Limits of y-axis: The upper and lower limits of the y-axis can be set using `y_lim` and `y_lim_min` parameters.
        6. Logarithmic scale: If `to_log` is set to True, the y-axis will be in logarithmic scale.
        7. Display of individual data points: The user can choose to display individual data points in each box plot
        by setting `show_individual_dots` to True.
        8. Data transformation: The data can be transformed to percentages using `convert_to_percent` parameter.
        9. Display of sample information: The user can choose to display information about the number of samples in each
        box plot by setting `show_sample_info` to "None", "All", or "Average".

        The function creates box plots for each combination of model and uncertainty type. It can save the resulting plot
        to a specified location.



        Args:
            cmaps (List[str]): Colors for the box plots.
            target_uncert_dicts (Dict[str, List[List[float]]]): Dictionary with lists of [error, uncertainty values] for all targets
            and corresponding data.
            uncertainty_types_list (List[List[str]]): List of lists containing uncertainty types.
            models (List[str]): List of models for which box plots are being made.
            x_axis_labels (List[str]): Labels for the x-axis.
            x_label (str): The label for the x-axis.
            y_label (str): The label for the y-axis.
            num_bins (int): The number of bins to be used for the box plot.
            list_comp_bool (bool): Flag to determine if list comprehension should be used.
            width (float): The width of the boxes in the box plot.
            y_lim_min (float): The minimum limit for the y-axis.
            font_size_1 (int): Font size for the first element.
            font_size_2 (int): Font size for the second element.
            show_sample_info (str): Information about the samples to be displayed. Default is "None".
            save_path (Optional[str]): The path where the plot will be saved. If None, the plot won't be saved. Default is None.
            y_lim (int): The maximum limit for the y-axis. Default is 120.
            convert_to_percent (bool): Flag to determine if data should be converted to percentages. Default is True.
            to_log (bool): Flag to determine if a logarithmic scale should be used. Default is False.
            show_individual_dots (bool): Flag to determine if individual data points should be shown. Default is True.

        Returns:
            None. The function displays and/or saves a plot.
        """
        # Implementation using the class methods  
        self._setup_plot()  
        orders = []
        bin_label_locs = []  
        outer_min_x_loc = 0.0  
        middle_min_x_loc = 0.0  
        inner_min_x_loc = 0.0  
          
        for i, (uncert_pair) in enumerate(uncertainty_types_list):  
            uncertainty_type = uncert_pair[0]  
              
            for j in range(num_bins):  
                inbetween_locs = []  
                average_samples_per_bin = []  
                  
                for hash_idx, model_type in enumerate(models):  
                    # Create legend patch for first bin only  
                    if j == 0:  
                        patch = self._create_legend_patch(cmaps, i, model_type, uncertainty_type, hash_idx)  
                        self.circ_patches.append(patch)  
                      
                    # Get model data  
                    dict_key = [x for x in target_uncert_dicts.keys()   
                              if (model_type in x) and (uncertainty_type in x)][0]  
                    model_data = target_uncert_dicts[dict_key]  
                      
                    # Process data based on list_comp_bool  
                    if list_comp_bool:  
                        all_b_data = [x for x in model_data[j] if x is not None]  
                    else:  
                        all_b_data = model_data[j]  

                    orders.append(model_type + uncertainty_type)    
                    # Calculate position  
                    x_loc = [outer_min_x_loc + inner_min_x_loc + middle_min_x_loc]  
                    inbetween_locs.append(x_loc[0])  
                      
                    # Convert to percentages if needed  
                    if convert_to_percent:  
                        displayed_data = [x * 100 for x in all_b_data]  
                    else:  
                        displayed_data = all_b_data  
                      
                    # Create boxplot with styling  
                    rect = self._create_boxplot_with_styling(displayed_data, x_loc, width, cmaps, i, hash_idx)  
                      
                    # Add individual dots if requested  
                    if show_individual_dots:  
                        self._add_individual_dots(displayed_data, x_loc, cmaps, uncertainty_types_list)  
                      
                    # Track max height for sample info positioning  
                    self.max_bin_height = max(max(rect["caps"][-1].get_ydata()), self.max_bin_height)  
                      
                    # Handle sample information tracking  
                    self._handle_sample_info(show_sample_info, model_data, all_b_data, rect, average_samples_per_bin)
                      
                    inner_min_x_loc += self.config.inner_spacing + width  
                  
                # Handle average sample info  
                self.handle_average_info(show_sample_info, inbetween_locs, average_samples_per_bin)  
                  
                # Calculate bin label locations  
                if list_comp_bool:  
                    bin_label_locs.extend(inbetween_locs)  
                else:  
                    bin_label_locs.append(np.mean(inbetween_locs))  
                  
                middle_min_x_loc += self.config.middle_spacing  
              
            # Calculate spacing between uncertainty types  
            middle_min_x_loc = self._calculate_spacing(num_bins, list_comp_bool, middle_min_x_loc)  
            outer_min_x_loc = self._calculate_spacing(num_bins, list_comp_bool, outer_min_x_loc)  

        self._format_plot(save_path, show_sample_info, to_log, y_lim, y_lim_min,  
                         convert_to_percent, x_label, y_label, font_size_1, font_size_2,  
                         bin_label_locs, x_axis_labels, num_bins, uncertainty_types_list)


        
    def box_plot_per_model(
        self,
        cmaps: List[str],
        target_uncert_dicts: Dict[str, List[List[float]]],
        uncertainty_types_list: List[List[str]],
        models: List[str],
        x_axis_labels: List[str],
        x_label: str,
        y_label: str,
        num_bins: int,
        show_sample_info: str = "None",
        save_path: Optional[str] = None,
        y_lim: int = 120,
        convert_to_percent: bool = True,
        to_log: bool = False,
        show_individual_dots: bool = True,
    ) -> None:
        """
        Generates a box plot to visualize and compare the performance of different models across uncertainty bins.

        This function creates a box plot for each model, grouped by uncertainty types, and displays the
        distribution of data within each bin. Individual data points can be shown as dots and additional
        information such as the percentage of samples per bin can be displayed on top of the box plots.

        Args:
            cmaps (List[str]): List of colors for matplotlib.
            target_uncert_dicts (Dict[str, List[List[float]]]): Dict of pandas dataframes for the data to display.
            uncertainty_types_list (List[List[str]]): List of lists describing the different uncertainty combinations to test.
            models (List[str]): The models we want to compare, keys in target_uncert_dicts.
            x_axis_labels (List[str]): List of strings for the x-axis labels, one for each bin.
            x_label (str): x-axis label.
            y_label (str): y-axis label.
            num_bins (int): Number of uncertainty bins.
            show_sample_info (str): Show sample information. Options: "None", "All", "Average". Default is "None".
            save_path (Optional[str]): Path to save plot to. If None, displays on screen (default=None).
            y_lim (int): y-axis limit of graph (default=120).
            convert_to_percent (bool): Flag to turn data into percentages. Default is True.
            to_log (bool): Flag to set y-axis scale to log. Default is False.
            show_individual_dots (bool): Flag to show individual data points as dots. Default is True.
        """ 
        self._setup_plot()
        orders = []  
        bin_label_locs = []
        outer_min_x_loc = 0.0
        middle_min_x_loc = 0.0
        inner_min_x_loc = 0.0
        
        for i, (uncert_pair) in enumerate(uncertainty_types_list):
            uncertainty_type = uncert_pair[0]
            for hash_idx, model_type in enumerate(models):
                inbetween_locs = []
                average_samples_per_bin = []
                
                for j in range(num_bins):
                    if j == 0:
                        patch = self._create_legend_patch(cmaps, i, model_type, uncertainty_type, hash_idx)
                        self.circ_patches.append(patch)
                    
                    dict_key = [x for x in target_uncert_dicts.keys() 
                            if (model_type in x) and (uncertainty_type in x)][0]
                    model_data = target_uncert_dicts[dict_key]
                    all_b_data = [x for x in model_data[j] if x is not None]
                    
                    orders.append(model_type + uncertainty_type)
                    
                    width = self.config.default_box_width
                    x_loc = [outer_min_x_loc + inner_min_x_loc + middle_min_x_loc]
                    inbetween_locs.append(x_loc[0])
                    
                    if convert_to_percent:
                        displayed_data = [x * 100 for x in all_b_data]
                    else:
                        displayed_data = all_b_data
                    
                    rect = self._create_boxplot_with_styling(displayed_data, x_loc, width, cmaps, i, hash_idx)
                    
                    if show_individual_dots:
                        self._add_individual_dots(displayed_data, x_loc, cmaps, uncertainty_types_list)
                    
                    self.max_bin_height = max(max(rect["caps"][-1].get_ydata()), self.max_bin_height)
                    
                    # Handle sample information tracking
                    self._handle_sample_info(show_sample_info, model_data, all_b_data, rect, average_samples_per_bin)
                    
                    inner_min_x_loc += self.config.inner_spacing + width
                
                # Handle average sample info
                self.handle_average_info(show_sample_info, inbetween_locs, average_samples_per_bin)
                
                bin_label_locs.extend(inbetween_locs)
                
                if num_bins > 9:
                    middle_min_x_loc += self.config.gap_large
                else:
                    middle_min_x_loc += self.config.gap_small
            
            outer_min_x_loc += self.config.outer_gap_large
        
        self._format_plot(save_path, show_sample_info, to_log, y_lim, -0.1,
                        convert_to_percent, x_label, y_label, 30, 30,
                        bin_label_locs, x_axis_labels, num_bins, uncertainty_types_list)

    def box_plot_comparing_q(
        self,
        target_uncert_dicts_list: List[Dict[str, List[List[float]]]],
        uncertainty_type_tuple: List,
        model: List[str],
        x_axis_labels: List[str],
        x_label: str,
        y_label: str,
        num_bins_display: int,
        hatch_type: str,
        color: str,
        show_sample_info: str = "None",
        save_path: Optional[str] = None,
        y_lim: int = 120,
        convert_to_percent: bool = True,
        to_log: bool = False,
        show_individual_dots: bool = True,
    ) -> None:
        """
        Creates a box plot of data, using Q (# Bins) on the x-axis.
        Only compares 1 model & 1 uncertainty type using Q on the x-axis.

        Args:
            target_uncert_dicts_list (List[Dict[str, List[List[float]]]]):
                List of Dict of pandas dataframe for the data to dsiplay, 1 for each value for Q.
            uncertainty_type_tuple (Tuple[str, str]):
                Tuple describing the single uncertainty/error type to display.
            model (Tuple[str, str]):
                The model we are comparing over our values of Q.
            x_axis_labels (List[str]):
                List of strings for the x-axis labels, one for each bin.
            x_label (str):
                X-axis label.
            y_label (str):
                Y-axis label.
            num_bins_display (List[int]):
                List of values of Q (#bins) we are comparing on our x-axis.
            hatch_type (str):
                Hatch type for the box plot.
            color (str):
                color for the box plot.
            show_sample_info (str, optional):
                Whether or not to show sample info on the plot.
                Options are "None", "All", or "Average". Defaults to "None".
            save_path (str, optional):
                Path to save plot to. If None, displays on screen. Defaults to None.
            y_lim (int, optional):
                Y-axis limit of graph. Defaults to 120.
            convert_to_percent (bool, optional):
                Whether to turn data to percentages. Defaults to True.
            to_log (bool, optional):
                Whether to set the y-axis to logarithmic scale. Defaults to False.
            show_individual_dots (bool, optional):
                Whether to show individual data points. Defaults to True.
        """   
        orders = []  # Keep for consistency with original
        self._setup_plot()

        bin_label_locs = []
        outer_min_x_loc = 0.0
        inner_min_x_loc = 0.0
        middle_min_x_loc = 0.0
        
        uncertainty_type = uncertainty_type_tuple[0][0]
        model_type = model[0]
        
        # Set legend
        patch = patches.Patch(
            hatch=hatch_type, facecolor=color,
            label=model_type + " " + uncertainty_type,
            edgecolor=self.config.box_edge_color
        )
        self.circ_patches.append(patch)
        
        for idx, q_value in enumerate(x_axis_labels):
            inbetween_locs = []
            target_uncert_dicts = target_uncert_dicts_list[idx]
            
            dict_key = [x for x in target_uncert_dicts.keys() 
                    if (model_type in x) and (uncertainty_type in x)][0]
            model_data = target_uncert_dicts[dict_key]
            average_samples_per_bin = []
            
            for j in range(len(model_data)):
                all_b_data = [x for x in model_data[j] if x is not None]
                
                orders.append(model_type + uncertainty_type)
                
                width = self.config.comparing_q_width_base * (4 / 5) ** idx
                x_loc = [outer_min_x_loc + inner_min_x_loc + middle_min_x_loc]
                inbetween_locs.append(x_loc[0])
                
                if convert_to_percent:
                    displayed_data = [x * 100 for x in all_b_data]
                else:
                    displayed_data = all_b_data
                
    
                rect = self._create_boxplot_with_styling(  
                    displayed_data, x_loc, width, [], 0, 0,   
                    custom_color=color, custom_hatch=hatch_type  
                )  
                
                self.max_bin_height = max(max(rect["caps"][-1].get_ydata()), self.max_bin_height)
                
                if show_individual_dots:
                    self._add_individual_dots(displayed_data, x_loc, [], [] ,alpha=self.config.dot_alpha_alt, custom_color=self.config.median_color)
                
                # Handle sample information
                self._handle_sample_info(show_sample_info, model_data, all_b_data, rect, average_samples_per_bin)

                inner_min_x_loc += 0.02 + width
            
            outer_min_x_loc += self.config.comparing_q_spacing
            bin_label_locs.append(np.mean(inbetween_locs))
            
            # Handle average sample info
            self.handle_average_info(show_sample_info, inbetween_locs, average_samples_per_bin)
        
        self._format_plot(save_path, show_sample_info, to_log, y_lim, -0.1,
                        convert_to_percent, x_label, y_label, 30, 25,
                        bin_label_locs, x_axis_labels, num_bins_display, 
                        uncertainty_type_tuple, comparing_q=True)


def plot_cumulative(
    cmaps: List[str],
    data_struct: Dict[str, pd.DataFrame],
    models: List[str],
    uncertainty_types: List[Tuple[str, str]],
    bins: Union[List[int], np.ndarray],
    title: str,
    compare_to_all: bool = False,
    save_path: Optional[str] = None,
    error_scaling_factor: float = 1,
) -> None:
    """
    Plots cumulative errors.

    Args:
        cmaps: A list of colors for matplotlib.
        data_struct: A dictionary containing the dataframes for each model.
        models: A list of models we want to compare, keys in `data_struct`.
        uncertainty_types: A list of lists describing the different uncertainty combinations to test.
        bins: A list of bins to show error form.
        title: The title of the plot.
        compare_to_all: Whether to compare the given subset of bins to all the data (default=False).
        save_path: The path to save plot to. If None, displays on screen (default=None).
        error_scaling_factor (float, optional): Scaling factor for error. Defaults to 1.0.
    """

    # make sure bins is a list and not a single value
    bins = [bins] if not isinstance(bins, (list, np.ndarray)) else bins

    plt.style.use("ggplot")

    _ = plt.figure()

    ax = plt.gca()
    plt.xticks(fontsize=10)
    plt.yticks(fontsize=10)

    ax.set_xlabel("Error (mm)", fontsize=10)
    ax.set_ylabel("Number of images in %", fontsize=10)
    plt.title(title)

    ax.set_xscale("log")
    line_styles = [":", "-", "dotted", "-."]
    for i, (uncert_pair) in enumerate(uncertainty_types):
        uncertainty = (uncert_pair)[0]
        color = cmaps[i]
        for hash_idx, model_type in enumerate(models):
            line = line_styles[hash_idx]

            # Filter only the bins selected
            dataframe = data_struct[model_type]
            model_un_errors = (
                dataframe[dataframe[uncertainty + " Uncertainty bins"].isin(bins)][uncertainty + " Error"].values
                * error_scaling_factor
            )

            p = 100 * np.arange(len(model_un_errors)) / (len(model_un_errors) - 1)

            sorted_errors = np.sort(model_un_errors)

            ax.plot(
                sorted_errors,
                p,
                label=model_type + " " + uncertainty,
                color=color,
                linestyle=line,
                dash_capstyle="round",
            )

            if compare_to_all:
                dataframe = data_struct[model_type]
                model_un_errors = dataframe[uncertainty + " Error"].values * error_scaling_factor

                p = 100 * np.arange(len(model_un_errors)) / (len(model_un_errors) - 1)

                sorted_errors = np.sort(model_un_errors)
                line = line_styles[len(models) + hash_idx]
                ax.plot(
                    sorted_errors,
                    p,
                    label=model_type + " " + uncertainty,
                    color=color,
                    linestyle=line,
                    dash_capstyle="round",
                )

    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles, labels, prop={"size": 10})
    plt.axvline(x=5, color=cmaps[3])

    for axis in [ax.xaxis, ax.yaxis]:
        axis.set_major_formatter(ScalarFormatter())

    plt.xticks([1, 2, 3, 4, 5, 10, 20, 30])

    ax.xaxis.label.set_color("black")
    ax.yaxis.label.set_color("black")

    ax.tick_params(axis="x", colors="black")
    ax.tick_params(axis="y", colors="black")

    if save_path is not None:
        plt.savefig(save_path + "cumulative_error.pdf", dpi=100, bbox_inches="tight", pad_inches=0.2)
        plt.close()
    else:
        plt.gcf().set_size_inches(16.0, 10.0)
        plt.show()
        plt.close()


def generate_fig_individual_bin_comparison(data: Tuple, display_settings: dict) -> None:
    """Generate figures to compare localization errors, error bounds accuracy, and Jaccard index across uncertainty bins.

    Args:
        data: A tuple containing various inputs needed to generate the figures, including:
            - uncertainty_error_pairs (List[Tuple[int, float]]): A list of tuples specifying the uncertainty thresholds
            and corresponding error thresholds to use for binning the data.
            - models_to_compare (List[str]): A list of model names to compare.
            - dataset (str): The name of the dataset being used.
            - target_indices (List[int]): A list of target indices to include in the analysis.
            - num_bins (int): The number of uncertainty bins to use.
            - cmaps (List[str]): A list of colormap names to use for the figures.
            - save_folder (str): The directory in which to save the generated figures.
            - save_file_preamble (str): A string to use as the prefix for the filenames of the generated figures.
            - combine_middle_bins (bool): Whether to combine the middle bins or not.
            - save_figures_bool (bool): Whether to save the generated figures or not. If False, displays instead
            - confidence_invert (bool): Whether to invert the confidence values to uncertainty or not.
            - samples_as_dots_bool (bool): Whether to show individual samples as dots in the box plots or not.
            - show_sample_info_mode (str): The mode for showing sample information in the box plots.
            - box_plot_error_lim (float): The y-axis limit for the error box plots.
            - show_individual_target_plots (bool): Whether to generate separate plots for each individual target.
            - interpret (bool): Whether to perform interpretation analysis i.e. visualization.
            - num_folds (int): The number of folds to use in cross-validation.
            - ind_targets_to_show (List[int]): A list of target indices to include in individual target plots.
            - error_scaling_factor (float, optional): Scaling factor for error. Defaults to 1.0.


        display_settings: A dictionary containing boolean flags indicating which figures to generate.

    Returns:
        None
    """
    logger = logging.getLogger("qbin")
    [
        uncertainty_error_pairs,
        models_to_compare,
        dataset,
        target_indices,
        num_bins,
        cmaps,
        save_folder,
        save_file_preamble,
        combine_middle_bins,
        save_figures_bool,
        confidence_invert,
        samples_as_dots_bool,
        show_sample_info_mode,
        box_plot_error_lim,
        show_individual_target_plots,
        interpret,
        num_folds,
        ind_targets_to_show,
        error_scaling_factor,
    ] = data

    # If combining the middle bins we just have the 2 edge bins, and the combined middle ones.

    bins_all_targets, bins_targets_sep, bounds_all_targets, bounds_targets_sep = generate_struct_for_qbin(
        models_to_compare, target_indices, save_folder, dataset
    )

    # Get mean errors bin-wise, get all errors concatenated together bin-wise, and seperate by target.
    all_error_data_dict = get_mean_errors(
        bins_all_targets,
        uncertainty_error_pairs,
        num_bins,
        target_indices,
        num_folds=num_folds,
        error_scaling_factor=error_scaling_factor,
        combine_middle_bins=combine_middle_bins,
    )
    all_error_data = all_error_data_dict["all mean error bins nosep"]

    all_bins_concat_targets_nosep_error = all_error_data_dict[
        "all error concat bins targets nosep"
    ]  # shape is [num bins]

    all_bins_concat_targets_sep_all_error = all_error_data_dict[
        "all error concat bins targets sep all"
    ]  # same as all_bins_concat_targets_sep_foldwise but folds are flattened to a single list

    # Get jaccard
    all_jaccard_data_dict = evaluate_jaccard(
        bins_all_targets,
        uncertainty_error_pairs,
        num_bins,
        target_indices,
        num_folds=num_folds,
        combine_middle_bins=combine_middle_bins,
    )
    all_jaccard_data = all_jaccard_data_dict["Jaccard All"]
    all_recall_data = all_jaccard_data_dict["Recall All"]
    all_precision_data = all_jaccard_data_dict["Precision All"]

    all_bins_concat_targets_sep_all_jacc = all_jaccard_data_dict[
        "all jacc concat bins targets sep all"
    ]  # same as all_bins_concat_targets_sep_foldwise but folds are flattened to a single list

    bound_return_dict = evaluate_bounds(
        bounds_all_targets,
        bins_all_targets,
        uncertainty_error_pairs,
        num_bins,
        target_indices,
        num_folds,
        combine_middle_bins=combine_middle_bins,
    )

    all_bound_data = bound_return_dict["Error Bounds All"]

    all_bins_concat_targets_sep_all_errorbound = bound_return_dict[
        "all errorbound concat bins targets sep all"
    ]  # same as all_bins_concat_targets_sep_foldwise but folds are flattened to a single list

    generate_summary_df(
        all_error_data_dict,
        [["all mean error bins nosep", "All Targets"]],
        "Mean error",
        os.path.join(save_folder, "target_errors.xlsx"),
    )

    if interpret:
        # If we have combined the middle bins, we are only displaying 3 bins (outer edges, and combined middle bins).
        if combine_middle_bins:
            num_bins_display = 3
        else:
            num_bins_display = num_bins

        if save_figures_bool:
            save_location = save_folder
        else:
            save_location = None

        # Plot piecewise linear regression for error/uncertainty prediction.
        if display_settings["correlation"]:
            _ = evaluate_correlations(
                bins_all_targets,
                uncertainty_error_pairs,
                cmaps,
                num_bins,
                confidence_invert,
                num_folds=num_folds,
                error_scaling_factor=error_scaling_factor,
                combine_middle_bins=combine_middle_bins,
                save_path=save_location,
                to_log=True,
            )

        # Plot cumulative error figure for all predictions
        if display_settings["cumulative_error"]:
            plot_cumulative(
                cmaps,
                bins_all_targets,
                models_to_compare,
                uncertainty_error_pairs,
                np.arange(num_bins),
                "Cumulative error for ALL predictions, dataset " + dataset,
                save_path=save_location,
                error_scaling_factor=error_scaling_factor,
            )
            # Plot cumulative error figure for B1 only predictions
            plot_cumulative(
                cmaps,
                bins_all_targets,
                models_to_compare,
                uncertainty_error_pairs,
                0,
                "Cumulative error for B1 predictions, dataset " + dataset,
                save_path=save_location,
                error_scaling_factor=error_scaling_factor,
            )

            # Plot cumulative error figure comparing B1 and ALL, for both models
            for model_type in models_to_compare:
                plot_cumulative(
                    cmaps,
                    bins_all_targets,
                    [model_type],
                    uncertainty_error_pairs,
                    0,
                    model_type + ". Cumulative error comparing ALL and B1, dataset " + dataset,
                    compare_to_all=True,
                    save_path=save_location,
                    error_scaling_factor=error_scaling_factor,
                )

        # Set x_axis labels for following plots.
        x_axis_labels = [r"$B_{{{}}}$".format(num_bins_display + 1 - (i + 1)) for i in range(num_bins_display + 1)]

        # get error bounds
        if display_settings["errors"]:
            # mean error concat for each bin
            logger.info("mean error concat all L")
            if save_figures_bool:
                if samples_as_dots_bool:
                    dotted_addition = "_dotted"
                else:
                    dotted_addition = "_undotted"
                save_location = os.path.join(
                    save_folder, save_file_preamble + dotted_addition + "_error_all_targets.pdf"
                )

            Box_plot().box_plot_per_model(
                cmaps,
                all_bins_concat_targets_nosep_error,
                uncertainty_error_pairs,
                models_to_compare,
                x_axis_labels=x_axis_labels,
                x_label="Uncertainty Thresholded Bin",
                y_label="Localization Error (mm)",
                num_bins=num_bins_display,
                convert_to_percent=False,
                show_sample_info=show_sample_info_mode,
                show_individual_dots=samples_as_dots_bool,
                y_lim=box_plot_error_lim,
                to_log=True,
                save_path=save_location,
            )

            if show_individual_target_plots:
                # plot the concatentated errors for each target seperately
                for idx_l, target_data in enumerate(all_bins_concat_targets_sep_all_error):
                    if idx_l in ind_targets_to_show or ind_targets_to_show == [-1]:
                        if save_figures_bool:
                            save_location = os.path.join(
                                save_folder,
                                save_file_preamble + dotted_addition + "_error_target_" + str(idx_l) + ".pdf",
                            )

                        logger.info("individual error for T%s", idx_l)

                        Box_plot().box_plot_per_model(
                            cmaps,
                            target_data,
                            uncertainty_error_pairs,
                            models_to_compare,
                            x_axis_labels=x_axis_labels,
                            x_label="Uncertainty Thresholded Bin",
                            y_label="Error (mm)",
                            num_bins=num_bins_display,
                            convert_to_percent=False,
                            show_sample_info=show_sample_info_mode,
                            show_individual_dots=samples_as_dots_bool,
                            y_lim=box_plot_error_lim,
                            to_log=True,
                            save_path=save_location,
                        )

            logger.info("Mean error")

            if save_figures_bool:
                save_location = os.path.join(
                    save_folder, save_file_preamble + dotted_addition + "mean_error_folds_all_targets.pdf"
                )

            Box_plot().box_plot_per_model(
                cmaps,
                all_error_data,
                uncertainty_error_pairs,
                models_to_compare,
                x_axis_labels=x_axis_labels,
                x_label="Uncertainty Thresholded Bin",
                y_label="Mean Error (mm)",
                num_bins=num_bins_display,
                convert_to_percent=False,
                y_lim=box_plot_error_lim,
                to_log=True,
                save_path=save_location,
            )

        # Plot Error Bound Accuracy
        if display_settings["error_bounds"]:
            logger.info(" errorbound acc for all targets.")
            if save_figures_bool:
                save_location = os.path.join(save_folder, save_file_preamble + "_errorbound_all_targets.pdf")

            Box_plot().generic_box_plot_loop(
                cmaps,
                all_bound_data,
                uncertainty_error_pairs,
                models_to_compare,
                x_axis_labels=x_axis_labels,
                x_label="Uncertainty Thresholded Bin",
                y_label="Error Bound Accuracy (%)",
                num_bins=num_bins_display,
                save_path=save_location,
                y_lim=120,
                width=0.2,
                y_lim_min=-2,
                font_size_1=30,
                font_size_2=30,
                show_individual_dots=False,
                list_comp_bool=False,
            )

            if show_individual_target_plots:
                # plot the concatentated error bounds for each target seperately
                for idx_l, target_data in enumerate(all_bins_concat_targets_sep_all_errorbound):
                    if idx_l in ind_targets_to_show or ind_targets_to_show == [-1]:
                        if save_figures_bool:
                            save_location = os.path.join(
                                save_folder, save_file_preamble + "_errorbound_target_" + str(idx_l) + ".pdf"
                            )

                        logger.info("individual errorbound acc for T%s", idx_l)

                        Box_plot().generic_box_plot_loop(
                            cmaps,
                            target_data,
                            uncertainty_error_pairs,
                            models_to_compare,
                            x_axis_labels=x_axis_labels,
                            x_label="Uncertainty Thresholded Bin",
                            y_label="Error Bound Accuracy (%)",
                            num_bins=num_bins_display,
                            save_path=save_location,
                            y_lim=120,
                            width=0.2,
                            y_lim_min=-2,
                            font_size_1=30,
                            font_size_2=30,
                            show_individual_dots=False,
                            list_comp_bool=False,
                        )

        # Plot Jaccard Index
        if display_settings["jaccard"]:
            logger.info("Plot jaccard for all targets.")
            if save_figures_bool:
                save_location = os.path.join(save_folder, save_file_preamble + "_jaccard_all_targets.pdf")

            Box_plot().generic_box_plot_loop(
                cmaps,
                all_jaccard_data,
                uncertainty_error_pairs,
                models_to_compare,
                x_axis_labels=x_axis_labels,
                x_label="Uncertainty Thresholded Bin",
                y_label="Jaccard Index (%)",
                num_bins=num_bins_display,
                save_path=save_location,
                y_lim=70,
                width=0.2,
                y_lim_min=-2,
                font_size_1=30,
                font_size_2=30,
                show_individual_dots=False,
                list_comp_bool=False,
            )

            # mean recall for each bin
            if save_figures_bool:
                save_location = os.path.join(save_folder, save_file_preamble + "_recall_jaccard_all_targets.pdf")

            Box_plot().generic_box_plot_loop(
                cmaps,
                all_recall_data,
                uncertainty_error_pairs,
                models_to_compare,
                x_axis_labels=x_axis_labels,
                x_label="Uncertainty Thresholded Bin",
                y_label="Ground Truth Bins Recall",
                num_bins=num_bins_display,
                convert_to_percent=True,
                save_path=save_location,
                y_lim=120,
                width=0.2,
                y_lim_min=-2,
                font_size_1=30,
                font_size_2=30,
                show_individual_dots=False,
                list_comp_bool=False,
            )

            # mean precision for each bin
            if save_figures_bool:
                save_location = os.path.join(save_folder, save_file_preamble + "_precision_jaccard_all_targets.pdf")

            Box_plot().generic_box_plot_loop(
                cmaps,
                all_precision_data,
                uncertainty_error_pairs,
                models_to_compare,
                x_axis_labels=x_axis_labels,
                x_label="Uncertainty Thresholded Bin",
                y_label="Ground Truth Bins Precision",
                num_bins=num_bins_display,
                convert_to_percent=True,
                save_path=save_location,
                y_lim=120,
                width=0.2,
                y_lim_min=-2,
                font_size_1=30,
                font_size_2=30,
                show_individual_dots=False,
                list_comp_bool=False,
            )

            if show_individual_target_plots:
                # plot the jaccard index for each target seperately

                for idx_l, target_data in enumerate(all_bins_concat_targets_sep_all_jacc):
                    if idx_l in ind_targets_to_show or ind_targets_to_show == [-1]:
                        if save_figures_bool:
                            save_location = os.path.join(
                                save_folder, save_file_preamble + "jaccard_target_" + str(idx_l) + ".pdf"
                            )

                        logger.info("individual jaccard for T%s", idx_l)

                        Box_plot().generic_box_plot_loop(
                            cmaps,
                            target_data,
                            uncertainty_error_pairs,
                            models_to_compare,
                            x_axis_labels=x_axis_labels,
                            x_label="Uncertainty Thresholded Bin",
                            y_label="Jaccard Index (%)",
                            num_bins=num_bins_display,
                            save_path=save_location,
                            y_lim=70,
                            width=0.2,
                            y_lim_min=-2,
                            font_size_1=30,
                            font_size_2=30,
                            show_individual_dots=False,
                            list_comp_bool=False,
                        )


def generate_fig_comparing_bins(
    data: Tuple,
    display_settings: Dict[str, Any],
) -> None:
    """
    Generate figures comparing localization error, error bounds accuracy, and Jaccard index for different binning
    configurations.

    Args:
        data (Tuple): A tuple containing various inputs needed to generate the figures. The tuple should include the following elements:
            - uncertainty_error_pair (Tuple[float, float]): A tuple representing the mean and standard deviation of
            the noise uncertainty used during training and evaluation.
            - model (str): The name of the model being evaluated.
            - dataset (str): The name of the dataset being used.
            - targets (List[int]): A list of target indices being evaluated.
            - all_values_q (List[int]): A list of integers representing the number of bins being used for each evaluation.
            - cmaps (List[str]): A list of colormap names to use for plotting.
            - all_fitted_save_paths (List[str]): A list of file paths where the binned data is stored.
            - save_folder (str): The directory where the figures should be saved.
            - save_file_preamble (str): The prefix to use for all figure file names.
            - combine_middle_bins (bool): Whether to combine the middle bins or not.
            - save_figures_bool (bool): Whether to save the generated figures or not. If false, shows instead.
            - samples_as_dots_bool (bool): Whether to show individual samples as dots in the box plots or not.
            - show_sample_info_mode (str): The mode for showing sample information in the box plots.
            - box_plot_error_lim (float): The y-axis limit for the error box plots.
            - show_individual_target_plots (bool): Whether to generate individual plots for each target.
            - interpret (bool): Whether the results are being interpreted.
            - num_folds (int): The number of cross-validation folds to use.
            - ind_targets_to_show (List[int]): A list of target indices to show in individual plots.
            - error_scaling_factor (float, optional): Scaling factor for error. Defaults to 1.0.

        display_settings: Dictionary containing the following keys:
            - 'hatch': String representing the type of hatch pattern to use in the plots.
            - 'color': String representing the color to use for the plots.

    Returns:
        None.
    """

    # Unpack data and logging settings
    [
        uncertainty_error_pair,
        model,
        dataset,
        targets,
        all_values_q,
        cmaps,
        all_fitted_save_paths,
        save_folder,
        save_file_preamble,
        combine_middle_bins,  # cfg["PIPELINE"]["COMBINE_MIDDLE_BINS"]
        save_figures_bool,  # cfg["OUTPUT"]["SAVE_FIGURES"]
        samples_as_dots_bool,  # cfg["BOXPLOT"]["SAMPLES_AS_DOTS"]
        show_sample_info_mode,  # cfg["BOXPLOT"]["SHOW_SAMPLE_INFO_MODE"]
        box_plot_error_lim,  # cfg["BOXPLOT"]["ERROR_LIM"]
        show_individual_target_plots,
        interpret,
        num_folds,
        ind_targets_to_show,
        error_scaling_factor,
    ] = data

    logger = logging.getLogger("qbin")

    hatch = display_settings["hatch"]
    color = display_settings["color"]

    # increse dimension of these for compatibility with future methods
    model_list = [model]
    uncertainty_error_pair_list = [uncertainty_error_pair]

    # If combining the middle bins we just have the 2 edge bins, and the combined middle ones.

    all_error_data = []
    all_error_target_sep = []
    all_bins_concat_targets_nosep_error = []
    all_bins_concat_targets_sep_foldwise_error = []
    all_bins_concat_targets_sep_all_error = []
    all_jaccard_data = []
    all_recall_data = []
    all_precision_data = []
    all_bins_concat_targets_sep_foldwise_jacc = []
    all_bins_concat_targets_sep_all_jacc = []
    all_bound_data = []
    all_bins_concat_targets_sep_foldwise_errorbound = []
    all_bins_concat_targets_sep_all_errorbound = []

    for idx, num_bins in enumerate(all_values_q):
        saved_bins_path_pre = all_fitted_save_paths[idx]

        bins_all_targets, bins_targets_sep, bounds_all_targets, bounds_targets_sep = generate_struct_for_qbin(
            model_list, targets, saved_bins_path_pre, dataset
        )

        # Get mean errors bin-wise, get all errors concatenated together bin-wise, and seperate by target.
        all_error_data_dict = get_mean_errors(
            bins_all_targets,
            uncertainty_error_pair_list,
            num_bins,
            targets,
            num_folds=num_folds,
            error_scaling_factor=error_scaling_factor,
            combine_middle_bins=combine_middle_bins,
        )
        all_error_data.append(all_error_data_dict["all mean error bins nosep"])
        all_error_target_sep.append(all_error_data_dict["all mean error bins targets sep"])

        all_bins_concat_targets_nosep_error.append(
            all_error_data_dict["all error concat bins targets nosep"]
        )  # shape is [num bins]
        all_bins_concat_targets_sep_foldwise_error.append(
            all_error_data_dict["all error concat bins targets sep foldwise"]
        )  # shape is [num targets][num bins]
        all_bins_concat_targets_sep_all_error.append(
            all_error_data_dict["all error concat bins targets sep all"]
        )  # same as all_bins_concat_targets_sep_foldwise but folds are flattened to a single list

        all_jaccard_data_dict = evaluate_jaccard(
            bins_all_targets,
            uncertainty_error_pair_list,
            num_bins,
            targets,
            num_folds=num_folds,
            combine_middle_bins=combine_middle_bins,
        )
        all_jaccard_data.append(all_jaccard_data_dict["Jaccard All"])
        all_recall_data.append(all_jaccard_data_dict["Recall All"])
        all_precision_data.append(all_jaccard_data_dict["Precision All"])
        all_bins_concat_targets_sep_foldwise_jacc.append(
            all_jaccard_data_dict["all jacc concat bins targets sep foldwise"]
        )  # shape is [num targets][num bins]
        all_bins_concat_targets_sep_all_jacc.append(
            all_jaccard_data_dict["all jacc concat bins targets sep all"]
        )  # same as all_bins_concat_targets_sep_foldwise but folds are flattened to a single list

        bound_return_dict = evaluate_bounds(
            bounds_all_targets,
            bins_all_targets,
            uncertainty_error_pair_list,
            num_bins,
            targets,
            num_folds,
            combine_middle_bins=combine_middle_bins,
        )

        all_bound_data.append(bound_return_dict["Error Bounds All"])
        all_bins_concat_targets_sep_foldwise_errorbound.append(
            bound_return_dict["all errorbound concat bins targets sep foldwise"]
        )  # shape is [num targets][num bins]
        all_bins_concat_targets_sep_all_errorbound.append(
            bound_return_dict["all errorbound concat bins targets sep all"]
        )  # same as all_bins_concat_targets_sep_foldwise but folds are flattened to a single list

    if interpret:
        # If we have combined the middle bins, we are only displaying 3 bins (outer edges, and combined middle bins).
        if combine_middle_bins:
            num_bins_display = 3
        else:
            num_bins_display = num_bins

        # Set x_axis labels for following plots.
        x_axis_labels = [str(x) for x in all_values_q]
        save_location = None

        # get error bounds

        if display_settings["errors"]:
            # mean error concat for each bin
            logger.info("mean error concat all L")
            if save_figures_bool:
                if samples_as_dots_bool:
                    dotted_addition = "_dotted"
                else:
                    dotted_addition = "_undotted"
                save_location = os.path.join(
                    save_folder, save_file_preamble + dotted_addition + "_error_all_targets.pdf"
                )

            Box_plot().box_plot_comparing_q(
                all_bins_concat_targets_nosep_error,
                uncertainty_error_pair_list,
                model_list,
                hatch_type=hatch,
                color=color,
                x_axis_labels=x_axis_labels,
                x_label="Q (# Bins)",
                y_label="Localization Error (mm)",
                num_bins_display=num_bins_display,
                convert_to_percent=False,
                show_sample_info=show_sample_info_mode,
                show_individual_dots=samples_as_dots_bool,
                y_lim=box_plot_error_lim,
                to_log=True,
                save_path=save_location,
            )

            if show_individual_target_plots:
                # plot the concatentated errors for each target seperately. Must transpose the iteration.
                for target_idx in targets:
                    target_data = [x[target_idx] for x in all_bins_concat_targets_sep_all_error]

                    if target_idx in ind_targets_to_show or ind_targets_to_show == [-1]:
                        if save_figures_bool:
                            save_location = os.path.join(
                                save_folder,
                                save_file_preamble + dotted_addition + "_error_target_" + str(target_idx) + ".pdf",
                            )

                        logger.info("individual error for T%s", target_idx)
                        Box_plot().box_plot_comparing_q(
                            target_data,
                            uncertainty_error_pair_list,
                            model_list,
                            hatch_type=hatch,
                            color=color,
                            x_axis_labels=x_axis_labels,
                            x_label="Q (# Bins)",
                            y_label="Localization Error (mm)",
                            num_bins_display=num_bins_display,
                            convert_to_percent=False,
                            show_sample_info=show_sample_info_mode,
                            show_individual_dots=samples_as_dots_bool,
                            y_lim=box_plot_error_lim,
                            to_log=True,
                            save_path=save_location,
                        )

            if save_figures_bool:
                save_location = os.path.join(
                    save_folder, save_file_preamble + dotted_addition + "mean_error_folds_all_targets.pdf"
                )
            Box_plot().box_plot_comparing_q(
                all_error_data,
                uncertainty_error_pair_list,
                model_list,
                hatch_type=hatch,
                color=color,
                x_axis_labels=x_axis_labels,
                x_label="Q (# Bins)",
                y_label="Mean Error (mm)",
                num_bins_display=num_bins_display,
                convert_to_percent=False,
                show_sample_info="None",
                show_individual_dots=False,
                y_lim=box_plot_error_lim,
                to_log=True,
                save_path=save_location,
            )

        # Plot Error Bound Accuracy

        if display_settings["error_bounds"]:
            logger.info(" errorbound acc for all targets.")
            if save_figures_bool:
                save_location = os.path.join(save_folder, save_file_preamble + "_errorbound_all_targets.pdf")

            Box_plot().box_plot_comparing_q(
                all_bound_data,
                uncertainty_error_pair_list,
                model_list,
                hatch_type=hatch,
                color=color,
                x_axis_labels=x_axis_labels,
                x_label="Q (# Bins)",
                y_label="Error Bound Accuracy (%)",
                num_bins_display=num_bins_display,
                convert_to_percent=True,
                show_sample_info="None",
                show_individual_dots=False,
                y_lim=100,
                save_path=save_location,
            )

            if show_individual_target_plots:
                # plot the concatentated errors for each target seperately. Must transpose the iteration.
                for target_idx in targets:
                    target_data = [x[target_idx] for x in all_bins_concat_targets_sep_all_errorbound]

                    if target_idx in ind_targets_to_show or ind_targets_to_show == [-1]:
                        if save_figures_bool:
                            save_location = os.path.join(
                                save_folder, save_file_preamble + "_errorbound_target_" + str(target_idx) + ".pdf"
                            )

                        logger.info("individual errorbound acc for T%s", target_idx)
                        Box_plot().box_plot_comparing_q(
                            target_data,
                            uncertainty_error_pair_list,
                            model_list,
                            hatch_type=hatch,
                            color=color,
                            x_axis_labels=x_axis_labels,
                            x_label="Q (# Bins)",
                            y_label="Error Bound Accuracy (%)",
                            num_bins_display=num_bins_display,
                            convert_to_percent=True,
                            show_individual_dots=False,
                            y_lim=100,
                            save_path=save_location,
                        )

        # Plot Jaccard Index
        if display_settings["jaccard"]:
            logger.info("Plot jaccard for all targets.")
            if save_figures_bool:
                save_location = os.path.join(save_folder, save_file_preamble + "_jaccard_all_targets.pdf")

            Box_plot().box_plot_comparing_q(
                all_jaccard_data,
                uncertainty_error_pair_list,
                model_list,
                hatch_type=hatch,
                color=color,
                x_axis_labels=x_axis_labels,
                x_label="Q (# Bins)",
                y_label="Jaccard Index (%)",
                num_bins_display=num_bins_display,
                convert_to_percent=True,
                show_individual_dots=False,
                y_lim=70,
                save_path=save_location,
            )

            # mean recall for each bin
            logger.info("Plot recall for all targets.")

            if save_figures_bool:
                save_location = os.path.join(save_folder, save_file_preamble + "_recall_jaccard_all_targets.pdf")
            Box_plot().box_plot_comparing_q(
                all_recall_data,
                uncertainty_error_pair_list,
                model_list,
                hatch_type=hatch,
                color=color,
                x_axis_labels=x_axis_labels,
                x_label="Q (# Bins)",
                y_label="Ground Truth Bin Recall (%)",
                num_bins_display=num_bins_display,
                convert_to_percent=True,
                show_individual_dots=False,
                y_lim=120,
                save_path=save_location,
            )

            # mean precision for each bin
            logger.info("Plot precision for all targets.")

            if save_figures_bool:
                save_location = os.path.join(save_folder, save_file_preamble + "_precision_jaccard_all_targets.pdf")
            Box_plot().box_plot_comparing_q(
                all_precision_data,
                uncertainty_error_pair_list,
                model_list,
                hatch_type=hatch,
                color=color,
                x_axis_labels=x_axis_labels,
                x_label="Q (# Bins)",
                y_label="Ground Truth Bin Precision (%)",
                num_bins_display=num_bins_display,
                convert_to_percent=True,
                show_individual_dots=False,
                y_lim=120,
                save_path=save_location,
            )

            if show_individual_target_plots:
                # plot the concatentated errors for each target seperately. Must transpose the iteration.
                for target_idx in targets:
                    target_data = [x[target_idx] for x in all_bins_concat_targets_sep_all_jacc]

                    if target_idx in ind_targets_to_show or ind_targets_to_show == [-1]:
                        if save_figures_bool:
                            save_location = os.path.join(
                                save_folder, save_file_preamble + "jaccard_target_" + str(target_idx) + ".pdf"
                            )

                        logger.info("individual jaccard for T%s", target_idx)
                        Box_plot().box_plot_comparing_q(
                            target_data,
                            uncertainty_error_pair_list,
                            model_list,
                            hatch_type=hatch,
                            color=color,
                            x_axis_labels=x_axis_labels,
                            x_label="Q (# Bins)",
                            y_label="Jaccard Index (%)",
                            num_bins_display=num_bins_display,
                            convert_to_percent=True,
                            show_individual_dots=False,
                            y_lim=70,
                            save_path=save_location,
                        )
