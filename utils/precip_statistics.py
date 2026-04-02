"""
precip_statistics.py
Конвертация MATLAB precip_statistics.m → Python

Формирует текстовую фразу об осадках по категориальным полям
(дождь, снег, ледяной дождь, ледяная крупа).
"""

import numpy as np


def precip_statistics(
    freeze_rain: np.ndarray,
    ice_pell: np.ndarray,
    rain: np.ndarray,
    snow: np.ndarray,
) -> str:
    """
    Parameters
    ----------
    freeze_rain : np.ndarray  — категориальный признак ледяного дождя (0/1)
    ice_pell    : np.ndarray  — категориальный признак ледяной крупы (0/1)
    rain        : np.ndarray  — категориальный признак дождя (0/1)
    snow        : np.ndarray  — категориальный признак снега (0/1)

    Returns
    -------
    precip_final : str — текстовая фраза об осадках
    """
    # Маска акватории (исключаем NaN — суша)
    valid_mask = ~np.isnan(rain)
    total_valid = np.sum(valid_mask)

    # Доля площади с осадками
    p_rain  = np.sum(rain[valid_mask]  > 0) / total_valid
    p_snow  = np.sum(snow[valid_mask]  > 0) / total_valid
    p_frain = np.sum(freeze_rain[valid_mask] > 0) / total_valid
    p_ice   = np.sum(ice_pell[valid_mask]    > 0) / total_valid

    # Пороги: 10% для обычных осадков, 5% для опасных
    threshold_std = 0.10
    threshold_adv = 0.05

    phenomena: list[str] = []

    # Логика «мокрого снега»
    if p_rain >= threshold_std and p_snow >= threshold_std:
        phenomena.append("мокрого снега")
    elif p_rain >= threshold_std:
        phenomena.append("дождя")
    elif p_snow >= threshold_std:
        phenomena.append("снега")

    # Опасные явления — добавляем поверх обычных
    if p_frain >= threshold_adv:
        phenomena.append("ледяного дождя")
    if p_ice >= threshold_adv:
        phenomena.append("ледяной крупы")

    if not phenomena:
        return "Без осадков."

    # Соединяем через запятую, последний через «и»
    if len(phenomena) == 1:
        joined = phenomena[0]
    else:
        joined = ", ".join(phenomena[:-1]) + " и " + phenomena[-1]

    return f"Ожидаются осадки в виде {joined}."
