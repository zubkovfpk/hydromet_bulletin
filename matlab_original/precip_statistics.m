function [precip_final]=precip_statistics(Freeze_Rain, Ice_Pell, Rain, Snow)

% Маска акватории
valid_mask = ~isnan(Rain);
total_valid = sum(valid_mask(:));

% Считаем покрытие
p_rain   = sum(Rain(valid_mask) > 0) / total_valid;
p_snow   = sum(Snow(valid_mask) > 0) / total_valid;
p_frain  = sum(Freeze_Rain(valid_mask) > 0) / total_valid;
p_ice    = sum(Ice_Pell(valid_mask) > 0) / total_valid;

% Пороги
threshold_std = 0.10; % 10% площади для обычных осадков
threshold_adv = 0.05; % 5% площади для опасных (ледяной дождь)

% Формирование списка явлений
list = {};

% Логика "Мокрого снега"
if p_rain >= threshold_std && p_snow >= threshold_std
    list{end+1} = 'мокрого снега';
elseif p_rain >= threshold_std
    list{end+1} = 'дождя';
elseif p_snow >= threshold_std
    list{end+1} = 'снега';
end

% Опасные явления добавляем всегда в дополнение
if p_frain >= threshold_adv
    list{end+1} = 'ледяного дождя';
end
if p_ice >= threshold_adv
    list{end+1} = 'ледяной крупы';
end

% 5. Результат
if isempty(list)
    precip_final = 'Без осадков.';
else
    % Соединение: "дождь, ледяной дождь и ледяная крупа"
    str_list = strjoin(list, ', ');
    str_list = regexprep(str_list, ', ([^,]+)$', ' и $1');

    precip_final = sprintf('Ожидаются осадки в виде %s.', str_list);
end

end