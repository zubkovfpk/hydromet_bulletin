function [final_dir, s_min, s_max]=wind_statistics(U_wind, V_wind)
% Исходные данные для примера (замените на свои матрицы 37x25)
% U, V — компоненты ветра

% Расчет модуля скорости
S = sqrt(U_wind.^2 + V_wind.^2);
S_vec = S(:);

% отсекаем крайние 10% с обеих сторон
v_min_threshold = quantile(S_vec, 0.10);
v_max_threshold = quantile(S_vec, 0.90);

% Создаем маску центральные 80% данных
mask = (S >= v_min_threshold) & (S <= v_max_threshold);

% Извлекаем данные только для типичных условий
U_typ = U_wind(mask);
V_typ = V_wind(mask);
S_typ = S(mask);

% перевод в метеорологические румбы (откуда дует)
% Формула перевода U,V в градусы (0-360, где 0 - Север)
angles = mod(180 + atan2d(U_typ, V_typ), 360);

% Разбивка на 8 румбов (каждый по 45 градусов, центр первого - 0)
% 1-С, 2-СВ, 3-В, 4-ЮВ, 5-Ю, 6-ЮЗ, 7-З, 8-СЗ
r_idx = floor(mod(angles + 22.5, 360) / 45) + 1;

% Статистика распределения направлений в процентах
counts = histcounts(r_idx, 1:9);
percents = (counts / numel(r_idx)) * 100;
[sorted_p, sorted_r] = sort(percents, 'descend'); % Сортировка по убыванию %

% Формирование текстового описания направления
dirs_text = {'северный', 'северо-восточный', 'восточный', 'юго-восточный', ...
             'южный', 'юго-западный', 'западный', 'северо-западный'};

% Если один румб > 35% И он существенно (в 1.5 раза) выше второго места
if sorted_p(1) >= 35 && (sorted_p(1) >= sorted_p(2) * 1.5)
    final_dir = [dirs_text{sorted_r(1)}];
    
% Если сумма двух первых > 50% и они сопоставимы
elseif (sorted_p(1) + sorted_p(2)) >= 50
    final_dir = [dirs_text{sorted_r(1)}, ' и ', dirs_text{sorted_r(2)}];
    
% Если сумма трех первых > 65%
elseif (sorted_p(1) + sorted_p(2) + sorted_p(3)) >= 65
    final_dir = [dirs_text{sorted_r(1)}, ', ', dirs_text{sorted_r(2)}, ...
                 ' и ', dirs_text{sorted_r(3)}];
    
% Если данные "размазаны" ровным слоем (лидер меньше 20-25%)
else
    final_dir = 'переменных направлений';
end

% Итоговая строка для отчета
s_min = round(v_min_threshold,1);
s_max = round(v_max_threshold,1);

end