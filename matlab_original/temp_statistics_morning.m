function [temp_phrase]=temp_statistics_morning(T_day, T_night)

%Исключаем сушу (NaN)
valid_day = T_day(~isnan(T_day));
valid_night = T_night(~isnan(T_night));


% Получаем реальный диапазон 5% - 95%
d_range = round(quantile(valid_day, [0.7, 0.93]));
n_range = round(quantile(valid_night, [0.7, 0.93]));

% Характерные (центральные) значения для сравнения дня и ночи
t_day_core = median(valid_day);
t_night_core = median(valid_night);

%  Разница дневных и ночных температур
delta_T = abs(t_day_core - t_night_core);

% Переход через ноль
cross_zero = (sign(d_range(1)) ~= sign(n_range(1))) || (sign(d_range(2)) ~= sign(n_range(2)));

% Формирование фразы
if delta_T > 5 || cross_zero
    % Формулировка 1: Раздельно
    temp_phrase = sprintf('Температура воздуха днем %d...%d, ночью %d...%d °С.', ...
        d_range(1), d_range(2), n_range(1), n_range(2));
else
    % Формулировка 2: Совместно (единый диапазон для суток)
    t_min = min(n_range(1), d_range(1));
    t_max = max(n_range(2), d_range(2));
    temp_phrase = sprintf('Температура воздуха днем и ночью %d...%d °С.', t_min, t_max);
end
end
