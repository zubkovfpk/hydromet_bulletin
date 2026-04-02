"""
temp_statistics.py
Конвертация MATLAB temp_statistics_morning.m / temp_statistics_evening.m → Python

Одна функция с параметром mode='morning' или 'evening'
контролирует порядок «день/ночь» в формулировке.
"""

import numpy as np


def _temp_phrase(T_first: np.ndarray, T_second: np.ndarray,
                 label_first: str, label_second: str) -> str:
    """
    Внутренняя функция: строит фразу о температуре.

    T_first  — массив температур первого периода
    T_second — массив температур второго периода
    label_first / label_second — «днём» / «ночью» или наоборот
    """
    valid_first  = T_first[~np.isnan(T_first)]
    valid_second = T_second[~np.isnan(T_second)]

    # Перцентили 70–93% (аналог MATLAB-оригинала)
    r_first  = np.round(np.quantile(valid_first,  [0.70, 0.93])).astype(int)
    r_second = np.round(np.quantile(valid_second, [0.70, 0.93])).astype(int)

    # Медианы для сравнения первого и второго периода
    t_first_core  = np.median(valid_first)
    t_second_core = np.median(valid_second)

    delta_T = abs(t_first_core - t_second_core)

    # Переход через 0°C
    cross_zero = (np.sign(r_first[0]) != np.sign(r_second[0])) or \
                 (np.sign(r_first[1]) != np.sign(r_second[1]))

    if delta_T > 5 or cross_zero:
        # Раздельные формулировки
        return (
            f"Температура воздуха {label_first} {r_first[0]}...{r_first[1]}, "
            f"{label_second} {r_second[0]}...{r_second[1]} °С."
        )
    else:
        # Единый диапазон для суток
        t_min = min(r_first[0], r_second[0])
        t_max = max(r_first[1], r_second[1])
        return (
            f"Температура воздуха {label_first} и {label_second} "
            f"{t_min}...{t_max} °С."
        )


def temp_statistics_morning(T_day: np.ndarray, T_night: np.ndarray) -> str:
    """
    Утренний бюллетень: сначала «днём», потом «ночью».

    Parameters
    ----------
    T_day   : np.ndarray — температура первых суток (°С)
    T_night : np.ndarray — температура следующих суток (ночь)
    """
    return _temp_phrase(T_day, T_night, "днём", "ночью")


def temp_statistics_evening(T_night: np.ndarray, T_day: np.ndarray) -> str:
    """
    Вечерний бюллетень: сначала «ночью», потом «днём».

    Parameters
    ----------
    T_night : np.ndarray — температура ночи (°С)
    T_day   : np.ndarray — температура следующего дня (°С)
    """
    return _temp_phrase(T_night, T_day, "ночью", "днём")
