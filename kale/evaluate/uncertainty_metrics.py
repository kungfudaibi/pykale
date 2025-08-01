"""
Authors: Lawrence Schobs, lawrenceschobs@gmail.com
Module from the implementation of L. A. Schobs, A. J. Swift and H. Lu, "Uncertainty Estimation for Heatmap-Based Landmark Localization,"
in IEEE Transactions on Medical Imaging, vol. 42, no. 4, pp. 1021-1034, April 2023, doi: 10.1109/TMI.2022.3222730.

Functions related to  evaluating the quantile binning method in terms of:
   A) Binning accuracy to ground truth bins: evaluate_jaccard, bin_wise_jaccard.
   B) Binning error bound accuracy: evaluate_bounds, bin_wise_bound_eval
   C) Binning attributes such as mean errors of bins (get_mean_errors, bin_wise_errors).

"""

from abc import abstractmethod
from typing import Dict, List

import numpy as np
import pandas as pd

from kale.evaluate.similarity_metrics import jaccard_similarity
from kale.prepdata.string_transform import strip_for_bound

class BaseUncertaintyEvaluator: 

    """
    Base class for uncertainty evaluation handlers.
    """ 
    def __init__(self, num_bins: int, targets: List[int], num_folds: int = 8, combine_middle_bins: bool = False):  
        self.num_bins = 3 if combine_middle_bins else num_bins  
        self.original_num_bins = num_bins  
        self.targets = targets  
        self.num_folds = num_folds  
        self.combine_middle_bins = combine_middle_bins  
  
    def _extract_fold_data(self, data_structs: pd.DataFrame, fold: int, uncertainty_type: str) -> Dict:  
        return FoldDataProcessor.extract_fold_data(data_structs, fold, uncertainty_type)  
  
  
    def evaluate(self, bin_predictions: Dict[str, pd.DataFrame], uncertainty_pairs: List, **kwargs) -> Dict:  
        results = self._initialize_results()  
        for model, data_structs in bin_predictions.items():  
            for uncert_pair in uncertainty_pairs:  
                uncertainty_type = uncert_pair[0]  
                fold_results = self._process_folds(data_structs, uncertainty_type, model=model, **kwargs)  
                self._aggregate_results(results, model, uncertainty_type, fold_results)  
        return self._finalize_results(results)  
  
    def _process_folds(self, data_structs: pd.DataFrame, uncertainty_type: str, **kwargs) -> Dict:  
        fold_accumulator = self._initialize_fold_accumulator()  
        for fold in range(self.num_folds):  
            fold_data = self._extract_fold_data(data_structs, fold, uncertainty_type)  
            fold_result = self._process_single_fold(fold_data, uncertainty_type, **kwargs)  
            self._accumulate_fold_result(fold_accumulator, fold_result)  
        return fold_accumulator  
  
    # Abstract methods that must be implemented by subclasses  
    @abstractmethod
    def _accumulate_fold_result(self, fold_accumulator: Dict, fold_result: Dict) -> None:  
        pass
    
    @abstractmethod  
    def _initialize_results(self) -> Dict:  
        pass  
  
    @abstractmethod  
    def _initialize_fold_accumulator(self) -> Dict:  
        pass  
  
    @abstractmethod  
    def _process_single_fold(self, fold_data: Dict, uncertainty_type: str, **kwargs) -> Dict:  
        pass  
  
    @abstractmethod  
    def _aggregate_results(self, results: Dict, model: str, uncertainty_type: str, fold_results: Dict) -> None:  
        pass  
  
    @abstractmethod  
    def _finalize_results(self, results: Dict) -> Dict:  
        pass
    
class FoldDataProcessor:
    """
    A utility class to handle processing of fold data for uncertainty evaluation.
    """  
    @staticmethod  
    def extract_fold_data(data_structs: pd.DataFrame, fold: int, uncertainty_type: str) -> Dict[str, pd.DataFrame]:  
        fold_filter = data_structs["Testing Fold"] == fold  
          
        fold_errors = data_structs[fold_filter][  
            ["uid", "target_idx", f"{uncertainty_type} Error"]  
        ]  
        fold_bins = data_structs[fold_filter][  
            ["uid", "target_idx", f"{uncertainty_type} Uncertainty bins"]  
        ]  
          
        return {  
            "errors": fold_errors,  
            "bins": fold_bins,  
            "filter": fold_filter  
        }  
      
    @staticmethod  
    def process_target_data(fold_errors: pd.DataFrame, fold_bins: pd.DataFrame,   
                          target_idx: int, uncertainty_type: str) -> Dict[str, Dict]:  
        target_filter = fold_errors["target_idx"] == target_idx  
          
        true_errors = fold_errors[target_filter][["uid", f"{uncertainty_type} Error"]]  
        pred_bins = fold_bins[target_filter][["uid", f"{uncertainty_type} Uncertainty bins"]]  
          
        return {  
            "errors_dict": dict(zip(true_errors.uid, true_errors[f"{uncertainty_type} Error"])),  
            "bins_dict": dict(zip(pred_bins.uid, pred_bins[f"{uncertainty_type} Uncertainty bins"]))  
        }


class BoundEvaluationHandler(BaseUncertaintyEvaluator):  
    
    def _initialize_results(self) -> Dict:  
        return {  
            "all_bound_percents": {},  
            "all_bound_percents_notargetsep": {},  
            "all_concat_errorbound_bins_target_sep_foldwise": [{} for _ in range(len(self.targets))],  
            "all_concat_errorbound_bins_target_sep_all": [{} for _ in range(len(self.targets))]  
        }  
      
    def _initialize_fold_accumulator(self) -> Dict:  
        return {  
            "fold_learned_bounds_mean_targets": [],  
            "fold_learned_bounds_mean_bins": [[] for _ in range(self.num_bins)],  
            "fold_learned_bounds_bins_targetsnotsep": [[] for _ in range(self.num_bins)],  
            "fold_all_bins_concat_targets_sep_foldwise": [  
                [[] for _ in range(self.num_bins)] for _ in range(len(self.targets))  
            ],  
            "fold_all_bins_concat_targets_sep_all": [  
                [[] for _ in range(self.num_bins)] for _ in range(len(self.targets))  
            ]  
        }  
      
    def _extract_fold_data(self, data_structs: pd.DataFrame, fold: int, uncertainty_type: str) -> Dict:  
        fold_data = FoldDataProcessor.extract_fold_data(data_structs, fold, uncertainty_type)  
        fold_data["fold_num"] = fold  
        return fold_data  
      
    def _process_single_fold(self, fold_data: Dict, uncertainty_type: str, **kwargs) -> Dict:  
        
        estimated_bounds = kwargs.get('estimated_bounds')
        model = kwargs.get('model')
        
        if not estimated_bounds or not model:
            raise ValueError("estimated_bounds and model are required for BoundEvaluationHandler")
        
        fold_bounds = strip_for_bound(  
            estimated_bounds[f"{model} Error Bounds"]  
            [estimated_bounds[f"{model} Error Bounds"]["fold"] == fold_data["fold_num"]]  
            [f"{uncertainty_type} Uncertainty bounds"].values  
        )  
          
        return bin_wise_bound_eval(  
            fold_bounds,  
            fold_data["errors"],  
            fold_data["bins"],  
            self.targets,  
            uncertainty_type,  
            self.num_bins,  
            show_fig=kwargs.get('show_fig', False)  
        )  
      
    def _accumulate_fold_result(self, fold_accumulator: Dict, fold_result: Dict) -> None:  
        fold_accumulator["fold_learned_bounds_mean_targets"].append(fold_result["mean all targets"])  
          
        for idx_bin in range(len(fold_result["mean all bins"])):  
            fold_accumulator["fold_learned_bounds_mean_bins"][idx_bin].append(fold_result["mean all bins"][idx_bin])  
            fold_accumulator["fold_learned_bounds_bins_targetsnotsep"][idx_bin] = (  
                fold_accumulator["fold_learned_bounds_bins_targetsnotsep"][idx_bin] + fold_result["mean all"][idx_bin]  
            )  
              
            for target_idx in range(len(self.targets)):  
                fold_accumulator["fold_all_bins_concat_targets_sep_foldwise"][target_idx][idx_bin] = (  
                    fold_accumulator["fold_all_bins_concat_targets_sep_foldwise"][target_idx][idx_bin]  
                    + fold_result["all bins concatenated targets seperated"][target_idx][idx_bin]  
                )  
                combined = (  
                    fold_accumulator["fold_all_bins_concat_targets_sep_all"][target_idx][idx_bin]  
                    + fold_result["all bins concatenated targets seperated"][target_idx][idx_bin]  
                )  
                fold_accumulator["fold_all_bins_concat_targets_sep_all"][target_idx][idx_bin] = combined  
      
    def _aggregate_results(self, results: Dict, model: str, uncertainty_type: str, fold_results: Dict) -> None:  
        # Reverse order so they are worst to best i.e. B5 -> B1  
        results["all_bound_percents"][model + " " + uncertainty_type] = fold_results["fold_learned_bounds_mean_bins"][::-1]  
        results["all_bound_percents_notargetsep"][model + " " + uncertainty_type] = fold_results["fold_learned_bounds_bins_targetsnotsep"][::-1]  
          
        for target_idx in range(len(results["all_concat_errorbound_bins_target_sep_foldwise"])):  
            results["all_concat_errorbound_bins_target_sep_foldwise"][target_idx][  
                model + " " + uncertainty_type  
            ] = fold_results["fold_all_bins_concat_targets_sep_foldwise"][target_idx]  
            results["all_concat_errorbound_bins_target_sep_all"][target_idx][  
                model + " " + uncertainty_type  
            ] = fold_results["fold_all_bins_concat_targets_sep_all"][target_idx]  
      
    def _finalize_results(self, results: Dict) -> Dict:  
        return {  
            "Error Bounds All": results["all_bound_percents"],  
            "all_bound_percents_notargetsep": results["all_bound_percents_notargetsep"],  
            "all errorbound concat bins targets sep foldwise": results["all_concat_errorbound_bins_target_sep_foldwise"],  
            "all errorbound concat bins targets sep all": results["all_concat_errorbound_bins_target_sep_all"],  
        }  
      


class JaccardEvaluationHandler(BaseUncertaintyEvaluator):  
    def _initialize_results(self) -> Dict:  
        return {  
            "all_jaccard_data": {},  
            "all_jaccard_bins_targets_sep": {},  
            "all_recall_data": {},  
            "all_recall_bins_targets_sep": {},  
            "all_precision_data": {},  
            "all_precision__bins_targets_sep": {},  
            "all_concat_jacc_bins_target_sep_foldwise": [{} for _ in range(len(self.targets))],  
            "all_concat_jacc_bins_target_sep_all": [{} for _ in range(len(self.targets))]  
        }
  
    def _initialize_fold_accumulator(self) -> Dict:  
        return {  
            "fold_mean_targets": [],  
            "fold_mean_bins": [[] for _ in range(self.num_bins)],  
            "fold_all_bins": [[] for _ in range(self.num_bins)],  
            "fold_mean_targets_recall": [],  
            "fold_mean_bins_recall": [[] for _ in range(self.num_bins)],  
            "fold_all_bins_recall": [[] for _ in range(self.num_bins)],  
            "fold_mean_targets_precision": [],  
            "fold_mean_bins_precision": [[] for _ in range(self.num_bins)],  
            "fold_all_bins_precision": [[] for _ in range(self.num_bins)],  
            "fold_all_bins_concat_targets_sep_foldwise": [  
                [[] for _ in range(self.num_bins)] for _ in range(len(self.targets))  
            ],  
            "fold_all_bins_concat_targets_sep_all": [  
                [[] for _ in range(self.num_bins)] for _ in range(len(self.targets))  
            ]  
        }  
      
    def _extract_fold_data(self, data_structs: pd.DataFrame, fold: int, uncertainty_type: str) -> Dict:  
        return FoldDataProcessor.extract_fold_data(data_structs, fold, uncertainty_type)  
      
    def _process_single_fold(self, fold_data: Dict, uncertainty_type: str, **kwargs) -> Dict:  
        # Handle combine_middle_bins logic  
        if self.combine_middle_bins:  
            num_bins_for_quantiles = self.original_num_bins  
            num_bins = 3  
        else:  
            num_bins_for_quantiles = self.num_bins  
            num_bins = self.num_bins  
              
        return bin_wise_jaccard(  
            fold_data["errors"],  
            fold_data["bins"],  
            num_bins,  
            num_bins_for_quantiles,  
            self.targets,  
            uncertainty_type,  
            self.combine_middle_bins  
        )  
      
    def _accumulate_fold_result(self, fold_accumulator: Dict, fold_result: Dict) -> None:  
        fold_accumulator["fold_mean_targets"].append(fold_result["mean all targets"])  
        fold_accumulator["fold_mean_targets_recall"].append(fold_result["mean all targets recall"])  
        fold_accumulator["fold_mean_targets_precision"].append(fold_result["mean all targets precision"])  
          
        for idx_bin in range(len(fold_result["mean all bins"])):  
            fold_accumulator["fold_mean_bins"][idx_bin].append(fold_result["mean all bins"][idx_bin])  
            fold_accumulator["fold_all_bins"][idx_bin] = (  
                fold_accumulator["fold_all_bins"][idx_bin] + fold_result["all bins"][idx_bin]  
            )  
              
            fold_accumulator["fold_mean_bins_recall"][idx_bin].append(fold_result["mean all bins recall"][idx_bin])  
            fold_accumulator["fold_all_bins_recall"][idx_bin] = (  
                fold_accumulator["fold_all_bins_recall"][idx_bin] + fold_result["all bins recall"][idx_bin]  
            )  
              
            fold_accumulator["fold_mean_bins_precision"][idx_bin].append(fold_result["mean all bins precision"][idx_bin])  
            fold_accumulator["fold_all_bins_precision"][idx_bin] = (  
                fold_accumulator["fold_all_bins_precision"][idx_bin] + fold_result["all bins precision"][idx_bin]  
            )  
              
            for target_idx in range(len(self.targets)):  
                fold_accumulator["fold_all_bins_concat_targets_sep_foldwise"][target_idx][idx_bin] = (  
                    fold_accumulator["fold_all_bins_concat_targets_sep_foldwise"][target_idx][idx_bin]  
                    + fold_result["all bins concatenated targets seperated"][target_idx][idx_bin]  
                )  
                combined = (  
                    fold_accumulator["fold_all_bins_concat_targets_sep_all"][target_idx][idx_bin]  
                    + fold_result["all bins concatenated targets seperated"][target_idx][idx_bin]  
                )  
                fold_accumulator["fold_all_bins_concat_targets_sep_all"][target_idx][idx_bin] = combined  
      
    def _aggregate_results(self, results: Dict, model: str, uncertainty_type: str, fold_results: Dict) -> None:  
        results["all_jaccard_data"][model + " " + uncertainty_type] = fold_results["fold_mean_bins"]  
        results["all_jaccard_bins_targets_sep"][model + " " + uncertainty_type] = fold_results["fold_all_bins"]  
          
        results["all_recall_data"][model + " " + uncertainty_type] = fold_results["fold_mean_bins_recall"]  
        results["all_recall_bins_targets_sep"][model + " " + uncertainty_type] = fold_results["fold_all_bins_recall"]  
          
        results["all_precision_data"][model + " " + uncertainty_type] = fold_results["fold_mean_bins_precision"]  
        results["all_precision__bins_targets_sep"][model + " " + uncertainty_type] = fold_results["fold_all_bins_precision"]  
          
        for target_idx in range(len(results["all_concat_jacc_bins_target_sep_foldwise"])):  
            results["all_concat_jacc_bins_target_sep_foldwise"][target_idx][  
                model + " " + uncertainty_type  
            ] = fold_results["fold_all_bins_concat_targets_sep_foldwise"][target_idx]  
            results["all_concat_jacc_bins_target_sep_all"][target_idx][  
                model + " " + uncertainty_type  
            ] = fold_results["fold_all_bins_concat_targets_sep_all"][target_idx]  
      
    def _finalize_results(self, results: Dict) -> Dict:  
        return {  
            "Jaccard All": results["all_jaccard_data"],  
            "Jaccard targets seperated": results["all_jaccard_bins_targets_sep"],  
            "Recall All": results["all_recall_data"],  
            "Recall targets seperated": results["all_recall_bins_targets_sep"],  
            "Precision All": results["all_precision_data"],  
            "Precision targets seperated": results["all_precision__bins_targets_sep"],  
            "all jacc concat bins targets sep foldwise": results["all_concat_jacc_bins_target_sep_foldwise"],  
            "all jacc concat bins targets sep all": results["all_concat_jacc_bins_target_sep_all"],  
        }
    
class ErrorEvaluationHandler(BaseUncertaintyEvaluator):  
    def _initialize_results(self) -> Dict:  
        """Initialize result containers specific to error evaluation"""  
        return {  
            "all_mean_error_bins": {},  
            "all_mean_error_bins_targets_sep": {},  
            "all_concat_error_bins_target_sep_foldwise": [{} for _ in range(len(self.targets))],  
            "all_concat_error_bins_target_sep_all": [{} for _ in range(len(self.targets))],  
            "all_concat_error_bins_target_nosep": {}  
        }  
    
    def _initialize_fold_accumulator(self) -> Dict:  
        return {  
            "fold_mean_targets": [],  
            "fold_mean_bins": [[] for _ in range(self.num_bins)],  
            "fold_all_bins": [[] for _ in range(self.num_bins)],  
            "fold_all_bins_concat_targets_sep_foldwise": [  
                [[] for _ in range(self.num_bins)] for _ in range(len(self.targets))  
            ],  
            "fold_all_bins_concat_targets_sep_all": [  
                [[] for _ in range(self.num_bins)] for _ in range(len(self.targets))  
            ],  
            "fold_all_bins_concat_targets_nosep": [[] for _ in range(self.num_bins)]  
        }  
      
    def _extract_fold_data(self, data_structs: pd.DataFrame, fold: int, uncertainty_type: str) -> Dict:  
        return FoldDataProcessor.extract_fold_data(data_structs, fold, uncertainty_type)  
      
    def _process_single_fold(self, fold_data: Dict, uncertainty_type: str, **kwargs) -> Dict:  
        error_scaling_factor = kwargs.get('error_scaling_factor', 1.0)
        return bin_wise_errors(  
            fold_data["errors"],  
            fold_data["bins"],  
            self.num_bins,  
            self.targets,  
            uncertainty_type,  
            error_scaling_factor  
        )  
      
    def _accumulate_fold_result(self, fold_accumulator: Dict, fold_result: Dict) -> None:  
        fold_accumulator["fold_mean_targets"].append(fold_result["mean all targets"])  
          
        for idx_bin in range(len(fold_result["mean all bins"])):  
            fold_accumulator["fold_mean_bins"][idx_bin].append(fold_result["mean all bins"][idx_bin])  
            fold_accumulator["fold_all_bins"][idx_bin] = (  
                fold_accumulator["fold_all_bins"][idx_bin] + fold_result["all bins"][idx_bin]  
            )  
              
            # Handle the complex concatenation logic for targets not separated  
            concat_no_sep = [x[idx_bin] for x in fold_result["all bins concatenated targets seperated"]]  
            flattened_concat_no_sep = [x for sublist in concat_no_sep for x in sublist]  
            flattened_concat_no_sep = [x for sublist in flattened_concat_no_sep for x in sublist]  
              
            fold_accumulator["fold_all_bins_concat_targets_nosep"][idx_bin] = (  
                fold_accumulator["fold_all_bins_concat_targets_nosep"][idx_bin] + flattened_concat_no_sep  
            )  
              
            for target_idx in range(len(self.targets)):  
                fold_accumulator["fold_all_bins_concat_targets_sep_foldwise"][target_idx][idx_bin] = (  
                    fold_accumulator["fold_all_bins_concat_targets_sep_foldwise"][target_idx][idx_bin]  
                    + fold_result["all bins concatenated targets seperated"][target_idx][idx_bin]  
                )  
                  
                if fold_result["all bins concatenated targets seperated"][target_idx][idx_bin] != []:  
                    combined = (  
                        fold_accumulator["fold_all_bins_concat_targets_sep_all"][target_idx][idx_bin]  
                        + fold_result["all bins concatenated targets seperated"][target_idx][idx_bin][0]  
                    )  
                else:  
                    combined = fold_accumulator["fold_all_bins_concat_targets_sep_all"][target_idx][idx_bin]  
                  
                fold_accumulator["fold_all_bins_concat_targets_sep_all"][target_idx][idx_bin] = combined  
      
    def _aggregate_results(self, results: Dict, model: str, uncertainty_type: str, fold_results: Dict) -> None:  
        # Reverse orderings to go from worst to best (B5 -> B1)  
        fold_mean_bins = fold_results["fold_mean_bins"][::-1]  
        fold_all_bins = fold_results["fold_all_bins"][::-1]  
        fold_all_bins_concat_targets_nosep = fold_results["fold_all_bins_concat_targets_nosep"][::-1]  
        fold_all_bins_concat_targets_sep_foldwise = [x[::-1] for x in fold_results["fold_all_bins_concat_targets_sep_foldwise"]]  
        fold_all_bins_concat_targets_sep_all = [x[::-1] for x in fold_results["fold_all_bins_concat_targets_sep_all"]]  
          
        results["all_mean_error_bins"][model + " " + uncertainty_type] = fold_mean_bins  
        results["all_mean_error_bins_targets_sep"][model + " " + uncertainty_type] = fold_all_bins  
        results["all_concat_error_bins_target_nosep"][model + " " + uncertainty_type] = fold_all_bins_concat_targets_nosep  
          
        for target_idx in range(len(fold_all_bins_concat_targets_sep_foldwise)):  
            results["all_concat_error_bins_target_sep_foldwise"][target_idx][  
                model + " " + uncertainty_type  
            ] = fold_all_bins_concat_targets_sep_foldwise[target_idx]  
            results["all_concat_error_bins_target_sep_all"][target_idx][  
                model + " " + uncertainty_type  
            ] = fold_all_bins_concat_targets_sep_all[target_idx]  
      
    def _finalize_results(self, results: Dict) -> Dict:  
        return {  
            "all mean error bins nosep": results["all_mean_error_bins"],  
            "all mean error bins targets sep": results["all_mean_error_bins_targets_sep"],  
            "all error concat bins targets nosep": results["all_concat_error_bins_target_nosep"],  
            "all error concat bins targets sep foldwise": results["all_concat_error_bins_target_sep_foldwise"],  
            "all error concat bins targets sep all": results["all_concat_error_bins_target_sep_all"],  
        }
    
    



    
def evaluate_bounds(estimated_bounds: Dict[str, pd.DataFrame], bin_predictions: Dict[str, pd.DataFrame],   
                   uncertainty_pairs: List, num_bins: int, targets: List[int],   
                   num_folds: int = 8, show_fig: bool = False, combine_middle_bins: bool = False) -> Dict:  
    """
    Evaluates error bounds for given uncertainty pairs and estimated bounds.

    Args:
        estimated_bounds (Dict[str, pd.DataFrame]): Dictionary of error bounds for each model.
        bin_predictions (Dict[str, pd.DataFrame]): Dictionary of bin predictions for each model.
        uncertainty_pairs (List[List[str]]): List of uncertainty pairs to be evaluated.
        num_bins (int): Number of bins to be used.
        targets (List[str]): List of targets to be evaluated.
        num_folds (int, optional): Number of folds for cross-validation. Defaults to 8.
        show_fig (bool, optional): Flag to show the figure. Defaults to False.
        combine_middle_bins (bool, optional): Flag to combine the middle bins. Defaults to False.

    Returns:
        Dict: Dictionary containing evaluation results.
    """

    evaluator = BoundEvaluationHandler(num_bins, targets, num_folds, combine_middle_bins)  

    return evaluator.evaluate(bin_predictions, uncertainty_pairs,   
                            estimated_bounds=estimated_bounds, show_fig=show_fig)  
  
def evaluate_jaccard(bin_predictions, uncertainty_pairs, num_bins, targets,   
                    num_folds=8, combine_middle_bins=False):  
    """
        Evaluate uncertainty estimation's ability to predict true error quantiles.
        For each bin, we calculate the jaccard index (JI) between the pred bins and GT error quantiles.
        We calculate the JI for each dictionary in the bin_predictions dict. For each bin, we calculate: a) the mean and
        std over all folds and all targets b) the mean and std for each target over all folds.

    Args:
        bin_predictions (Dict): dict of Pandas Dataframes where each dataframe has errors, predicted bins for all uncertainty measures for a model,
        uncertainty_pairs ([list]): list of lists describing the different uncert combinations to test,
        num_bins (int): Number of quantile bins,
        targets (list) list of targets to measure uncertainty estimation,
        num_folds (int): Number of folds,


    Returns:
        [Dict]: Dicts with JI for all targets combined and targets seperated.
    """ 
    evaluator = JaccardEvaluationHandler(num_bins, targets, num_folds, combine_middle_bins)  

    return evaluator.evaluate(bin_predictions, uncertainty_pairs)  
  
def get_mean_errors(bin_predictions: Dict[str, pd.DataFrame], uncertainty_pairs: List,   
                   num_bins: int, targets: List[int], num_folds: int = 8,   
                   error_scaling_factor: float = 1.0, combine_middle_bins: bool = False) -> Dict: 

    """
    Evaluate uncertainty estimation's mean error of each bin.
    For each bin, we calculate the mean localization error for each target and for all targets.
    We calculate the mean error for each dictionary in the bin_predictions dict. For each bin, we calculate: a) the mean
    and std over all folds and all targets b) the mean and std for each target over all folds.

    Args:
        bin_predictions (Dict): Dict of Pandas DataFrames where each DataFrame has errors, predicted bins for all
        uncertainty measures for a model.
        uncertainty_pairs (List[Tuple[str, str]]): List of tuples describing the different uncertainty combinations to test.
        num_bins (int): Number of quantile bins.
        targets (List[str]): List of targets to measure uncertainty estimation.
        num_folds (int, optional): Number of folds. Defaults to 8.
        error_scaling_factor (int, optional): Scale error factor. Defaults to 1.
        combine_middle_bins (bool, optional): Combine middle bins if True. Defaults to False.

    Returns:
        Dict[str, Union[Dict[str, List[List[float]]], List[Dict[str, List[float]]]]]: Dictionary with mean error for all
         targets combined and targets separated.
            Keys that are returned:
                "all mean error bins nosep":  For every fold, the mean error for each bin. All targets are combined in the same list.
                "all mean error bins targets sep":   For every fold, the mean error for each bin. Each target is in a separate list.
                "all error concat bins targets nosep":  For every fold, every error value in a list. Each target is in the same list. The list is flattened for all the folds.
                "all error concat bins targets sep foldwise":  For every fold, every error value in a list. Each target is in a separate list. Each list has a list of results by fold.
                "all error concat bins targets sep all": For every fold, every error value in a list. Each target is in a separate list. The list is flattened for all the folds.

    """ 
    evaluator = ErrorEvaluationHandler(num_bins, targets, num_folds, combine_middle_bins)  
    return evaluator.evaluate(bin_predictions, uncertainty_pairs,   
                            error_scaling_factor=error_scaling_factor)






def bin_wise_bound_eval(
    fold_bounds_all_targets: list,
    fold_errors: pd.DataFrame,
    fold_bins: pd.DataFrame,
    targets: list,
    uncertainty_type: str,
    num_bins: int = 5,
    show_fig: bool = False,
) -> dict:
    """
    Helper function for `evaluate_bounds`. Evaluates the accuracy of estimated error bounds for each quantile bin
    for a given uncertainty type, over a single fold and for multiple targets.

    Args:
        fold_bounds_all_targets (list): A list of lists of estimated error bounds for each target.
        fold_errors (pd.DataFrame): A Pandas DataFrame containing the true errors for this fold.
        fold_bins (pd.DataFrame): A Pandas DataFrame containing the predicted quantile bins for this fold.
        targets (list): A list of targets to measure uncertainty estimation.
        uncertainty_type (str): The name of the uncertainty type to calculate accuracy for.
        num_bins (int): The number of quantile bins.
        show_fig (bool): Whether to show a figure depicting error bound accuracy (default=False).

    Returns:
        dict: A dictionary containing the following error bound accuracy statistics:
              - 'mean all targets': The mean accuracy over all targets and quantile bins.
              - 'mean all bins': A list of mean accuracy values for each quantile bin (all targets included).
              - 'mean all': A list of accuracy values for each quantile bin and target, weighted by # targets in each bin.
              - 'all bins concatenated targets separated': A list of accuracy values for each quantile bin, concatenated
               for each target separately.

    Example:
        >>> bin_wise_bound_eval(fold_bounds_all_targets, fold_errors, fold_bins, [0,1], 'S-MHA', num_bins=5)
    """
    all_target_perc = []
    all_qs_perc: List[List[float]] = [[] for x in range(num_bins)]  #
    all_qs_size: List[List[float]] = [[] for x in range(num_bins)]

    all_qs_errorbound_concat_targets_sep: List[List[List[float]]] = [
        [[] for y in range(num_bins)] for x in range(len(targets))
    ]

    for i_ti, target_idx in enumerate(targets):
        true_errors_ti = fold_errors[(fold_errors["target_idx"] == target_idx)][["uid", uncertainty_type + " Error"]]
        pred_bins_ti = fold_bins[(fold_errors["target_idx"] == target_idx)][
            ["uid", uncertainty_type + " Uncertainty bins"]
        ]

        # Zip to dictionary
        true_errors_ti = dict(zip(true_errors_ti.uid, true_errors_ti[uncertainty_type + " Error"]))
        pred_bins_ti = dict(zip(pred_bins_ti.uid, pred_bins_ti[uncertainty_type + " Uncertainty bins"]))

        # The error bounds are from B1 -> B5 i.e. best quantile of predictions to worst quantile of predictions
        fold_bounds = fold_bounds_all_targets[i_ti]

        # For each bin, see what % of targets are between the error bounds.
        # If bin=0 then lower bound = 0, if bin=Q then no upper bound
        # Keep track of #samples in each bin for weighted mean.

        # turn dictionary of predicted bins into [[num_bins]] array
        pred_bins_keys = []
        pred_bins_errors = []
        for i in range(num_bins):
            inner_list_bin = list([key for key, val in pred_bins_ti.items() if str(i) == str(val)])
            inner_list_errors = []

            for id_ in inner_list_bin:
                inner_list_errors.append(list([val for key, val in true_errors_ti.items() if str(key) == str(id_)])[0])

            pred_bins_errors.append(inner_list_errors)
            pred_bins_keys.append(inner_list_bin)

        bins_acc = []
        bins_sizes = []
        for q in range((num_bins)):
            inner_bin_correct = 0

            inbin_errors = pred_bins_errors[q]

            for error in inbin_errors:
                if q == 0:
                    lower = 0
                    upper = fold_bounds[q]

                    if error <= upper and error > lower:
                        inner_bin_correct += 1

                elif q < (num_bins) - 1:
                    lower = fold_bounds[q - 1]
                    upper = fold_bounds[q]

                    if error <= upper and error > lower:
                        inner_bin_correct += 1

                else:
                    lower = fold_bounds[q - 1]
                    upper = 999999999999999999999999999999

                    if error > lower:
                        inner_bin_correct += 1

            if inner_bin_correct == 0:
                accuracy_bin = 0.0
            elif len(inbin_errors) == 0:
                accuracy_bin = 1.0
            else:
                accuracy_bin = inner_bin_correct / len(inbin_errors)
            bins_sizes.append(len(inbin_errors))
            bins_acc.append(accuracy_bin)

            all_qs_perc[q].append(accuracy_bin)
            all_qs_size[q].append(len(inbin_errors))
            all_qs_errorbound_concat_targets_sep[i_ti][q].append(accuracy_bin)

        # Weighted average over all bins
        weighted_mean_ti = 0.0
        total_weights = 0.0
        for l_idx in range(len(bins_sizes)):
            bin_acc = bins_acc[l_idx]
            bin_size = bins_sizes[l_idx]
            weighted_mean_ti += bin_acc * bin_size
            total_weights += bin_size
        weighted_ave = weighted_mean_ti / total_weights
        all_target_perc.append(weighted_ave)

    # Weighted average for each of the quantile bins.
    weighted_ave_binwise = []
    for binidx in range(len(all_qs_perc)):
        bin_accs = all_qs_perc[binidx]
        bin_asizes = all_qs_size[binidx]

        weighted_mean_bin = 0.0
        total_weights_bin = 0.0
        for l_idx in range(len(bin_accs)):
            b_acc = bin_accs[l_idx]
            b_siz = bin_asizes[l_idx]
            weighted_mean_bin += b_acc * b_siz
            total_weights_bin += b_siz

        # Avoid div by 0
        if weighted_mean_bin == 0 or total_weights_bin == 0:
            weighted_ave_bin = 0.0
        else:
            weighted_ave_bin = weighted_mean_bin / total_weights_bin
        weighted_ave_binwise.append(weighted_ave_bin)

    # No weighted average, just normal average
    normal_ave_bin_wise = []
    for binidx in range(len(all_qs_perc)):
        bin_accs = all_qs_perc[binidx]
        normal_ave_bin_wise.append(np.mean(bin_accs))

    return {
        "mean all targets": np.mean(all_target_perc),
        "mean all bins": weighted_ave_binwise,
        "mean all": all_qs_perc,
        "all bins concatenated targets seperated": all_qs_errorbound_concat_targets_sep,
    }




def bin_wise_errors(fold_errors, fold_bins, num_bins, targets, uncertainty_key, error_scaling_factor):
    """
    Helper function for get_mean_errors. Calculates the mean error for each bin and for each target.

    Args:
        fold_errors (Pandas Dataframe): Pandas Dataframe of errors for this fold.
        fold_bins (Pandas Dataframe): Pandas Dataframe of predicted quantile bins for this fold.
        num_bins (int): Number of quantile bins,
        targets (list) list of targets to measure uncertainty estimation,
        uncertainty_key (string): Name of uncertainty type to calculate accuracy for,


    Returns:
        [Dict]: Dict with mean error statistics.
    """

    all_target_error = []
    all_qs_error = [[] for x in range(num_bins)]
    all_qs_error_concat_targets_sep = [[[] for y in range(num_bins)] for x in range(len(targets))]

    for i, target_idx in enumerate(targets):
        true_errors_ti = fold_errors[(fold_errors["target_idx"] == target_idx)][["uid", uncertainty_key + " Error"]]
        pred_bins_ti = fold_bins[(fold_errors["target_idx"] == target_idx)][
            ["uid", uncertainty_key + " Uncertainty bins"]
        ]

        # Zip to dictionary
        true_errors_ti = dict(
            zip(true_errors_ti.uid, true_errors_ti[uncertainty_key + " Error"] * error_scaling_factor)
        )
        pred_bins_ti = dict(zip(pred_bins_ti.uid, pred_bins_ti[uncertainty_key + " Uncertainty bins"]))

        pred_bins_keys = []
        pred_bins_errors = []

        # This is saving them from best quantile of predictions to worst quantile of predictions in terms of uncertainty
        for j in range(num_bins):
            inner_list = list([key for key, val in pred_bins_ti.items() if str(j) == str(val)])
            inner_list_errors = []

            for id_ in inner_list:
                inner_list_errors.append(list([val for key, val in true_errors_ti.items() if str(key) == str(id_)])[0])

            pred_bins_errors.append(inner_list_errors)
            pred_bins_keys.append(inner_list)

        # Now for each bin, get the mean error
        inner_errors = []
        for bin in range(num_bins):
            # pred_b_keys = pred_bins_keys[bin]
            pred_b_errors = pred_bins_errors[bin]

            # test for empty bin, it would've created a mean_error==nan , so don't add it!
            if pred_b_errors == []:
                continue

            mean_error = np.mean(pred_b_errors)
            all_qs_error[bin].append(mean_error)
            all_qs_error_concat_targets_sep[i][bin].append(pred_b_errors)
            inner_errors.append(mean_error)

        all_target_error.append(np.mean(inner_errors))

    mean_all_targets = np.mean(all_target_error)
    mean_all_bins = []
    for x in all_qs_error:
        if x == []:
            mean_all_bins.append(None)
        else:
            mean_all_bins.append(np.mean(x))

    return {
        "mean all targets": mean_all_targets,
        "mean all bins": mean_all_bins,
        "all bins": all_qs_error,
        "all bins concatenated targets seperated": all_qs_error_concat_targets_sep,
    }


def bin_wise_jaccard(
    fold_errors: pd.DataFrame,
    fold_bins: pd.DataFrame,
    num_bins: int,
    num_bins_quantiles: int,
    targets: list,
    uncertainty_key: str,
    combine_middle_bins: bool,
) -> dict:
    """
    Helper function for evaluate_jaccard. Calculates the Jaccard Index statistics for each quantile bin and target.

    If combine_middle_bins is True, then the middle bins are combined into one bin. e.g. if num_bins_quantiles = 10,
    it will return 3 bins: 1, 2-9, 10.
    You may find the first bin and the last bin are the most accurate, so combining the middle bins may be useful.

    Args:
        fold_errors (Pandas Dataframe): Pandas Dataframe of errors for this fold.
        fold_bins (Pandas Dataframe): Pandas Dataframe of predicted quantile bins for this fold.
        num_bins (int): Number of quantile bins,
        targets (list) list of targets to measure uncertainty estimation,
        uncertainty_key (string): Name of uncertainty type to calculate accuracy for,


    Returns:
        [Dict]: Dict with JI statistics.

    Raises:
        None.

    Example:
        >>> bin_wise_jaccard(fold_errors, fold_bins, 10, 5, [0,1], 'S-MHA', True)
    """

    all_target_jacc: List[float] = []
    all_qs_jacc: List[List[float]] = [[] for x in range(num_bins)]

    all_qs_jacc_concat_targets_sep: List[List[List[float]]] = [
        [[] for y in range(num_bins)] for x in range(len(targets))
    ]

    all_target_recall: List[float] = []
    all_qs_recall: List[List[float]] = [[] for x in range(num_bins)]

    all_target_precision: List[float] = []
    all_qs_precision: List[List[float]] = [[] for x in range(num_bins)]

    for i, target_idx in enumerate(targets):
        true_errors_ti = fold_errors[(fold_errors["target_idx"] == target_idx)][["uid", uncertainty_key + " Error"]]
        pred_bins_ti = fold_bins[(fold_errors["target_idx"] == target_idx)][
            ["uid", uncertainty_key + " Uncertainty bins"]
        ]

        # Zip to dictionary
        true_errors_ti = dict(zip(true_errors_ti.uid, true_errors_ti[uncertainty_key + " Error"]))
        pred_bins_ti = dict(zip(pred_bins_ti.uid, pred_bins_ti[uncertainty_key + " Uncertainty bins"]))

        pred_bins_keys = []
        pred_bins_errors = []

        # This is saving them from best quantile of predictions to worst quantile of predictions in terms of uncertainty
        for j in range(num_bins):
            inner_list = list([key for key, val in pred_bins_ti.items() if str(j) == str(val)])
            inner_list_errors = []

            for id_ in inner_list:
                inner_list_errors.append(list([val for key, val in true_errors_ti.items() if str(key) == str(id_)])[0])

            pred_bins_errors.append(inner_list_errors)
            pred_bins_keys.append(inner_list)

        # Get the true error quantiles
        sorted_errors = [v for k, v in sorted(true_errors_ti.items(), key=lambda item: item[1])]

        quantiles = np.arange(1 / num_bins_quantiles, 1, 1 / num_bins_quantiles)[: num_bins_quantiles - 1]
        quantile_thresholds = [np.quantile(sorted_errors, q) for q in quantiles]

        # If we are combining the middle bins, combine the middle lists into 1 list.

        if combine_middle_bins:
            quantile_thresholds = [quantile_thresholds[0], quantile_thresholds[-1]]

        errors_groups = []
        key_groups = []

        for q in range(len(quantile_thresholds) + 1):
            inner_list_e = []
            inner_list_id = []
            for i_te, (id_, error) in enumerate(true_errors_ti.items()):
                if q == 0:
                    lower = 0
                    upper = quantile_thresholds[q]

                    if error <= upper:
                        inner_list_e.append(error)
                        inner_list_id.append(id_)

                elif q < len(quantile_thresholds):
                    lower = quantile_thresholds[q - 1]
                    upper = quantile_thresholds[q]

                    if error <= upper and error > lower:
                        inner_list_e.append(error)
                        inner_list_id.append(id_)

                else:
                    lower = quantile_thresholds[q - 1]
                    upper = 999999999999999999999999999999

                    if error > lower:
                        inner_list_e.append(error)
                        inner_list_id.append(id_)

            errors_groups.append(inner_list_e)
            key_groups.append(inner_list_id)

        # flip them so they go from B5 to B1
        pred_bins_keys = pred_bins_keys[::-1]
        pred_bins_errors = pred_bins_errors[::-1]
        errors_groups = errors_groups[::-1]
        key_groups = key_groups[::-1]

        # Now for each bin, get the jaccard similarity
        inner_jaccard_sims = []
        inner_recalls = []
        inner_precisions = []
        for bin in range(num_bins):
            pred_b_keys = pred_bins_keys[bin]
            gt_bins_keys = key_groups[bin]

            j_sim = jaccard_similarity(pred_b_keys, gt_bins_keys)
            all_qs_jacc[bin].append(j_sim)
            all_qs_jacc_concat_targets_sep[i][bin].append(j_sim)

            inner_jaccard_sims.append(j_sim)

            # If quantile threshold is the same as the last quantile threshold,
            # the GT set is empty (rare, but can happen if distribution of errors is quite uniform).
            if len(gt_bins_keys) == 0:
                recall = 1.0
                precision = 0.0
            else:
                recall = sum(el in gt_bins_keys for el in pred_b_keys) / len(gt_bins_keys)

                if len(pred_b_keys) == 0 and len(gt_bins_keys) > 0:
                    precision = 0.0
                else:
                    precision = sum(1 for x in pred_b_keys if x in gt_bins_keys) / len(pred_b_keys)

            inner_recalls.append(recall)
            inner_precisions.append(precision)
            all_qs_recall[bin].append(recall)
            all_qs_precision[bin].append(precision)

        all_target_jacc.append(np.mean(inner_jaccard_sims))
        all_target_recall.append(np.mean(inner_recalls))
        all_target_precision.append(np.mean(inner_precisions))

    return {
        "mean all targets": np.mean(all_target_jacc),
        "mean all bins": [np.mean(x) for x in all_qs_jacc],
        "all bins": all_qs_jacc,
        "mean all targets recall": np.mean(all_target_recall),
        "mean all bins recall": [np.mean(x) for x in all_qs_recall],
        "all bins recall": all_qs_recall,
        "mean all targets precision": np.mean(all_target_precision),
        "mean all bins precision": [np.mean(x) for x in all_qs_precision],
        "all bins precision": all_qs_precision,
        "all bins concatenated targets seperated": all_qs_jacc_concat_targets_sep,
    }
