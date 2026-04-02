clearvars; close all; clc;
tic;

import mlreportgen.dom.*

%% Получение данных
[Temp, Rain, Freeze_Rain, Ice_Pell, Snow, Wind_Gust, U_wind, V_wind, Vis] = collect_meteo_data();
[HWave, Start_Date, End_Date]=collect_wave_data();

%% Создание документа

doc=mlreportgen.dom.Document('Прогноз_вечер','docx');
%doc.HtmlLanguage = 'ru-RU';
spacingStyle = mlreportgen.dom.LineSpacing(1.0); 

% Отступы
spacer = mlreportgen.dom.Paragraph(' ');
spacer.Style = {mlreportgen.dom.OuterMargin('0pt', '0pt', '0pt', '0pt'), ...
                mlreportgen.dom.LineSpacing(1.0)};

% Заголовок документа "Бюллетень"

data=datestr(Start_Date,'dd.mm.yyyy'); % автоматическое обновление даты бюллетеня   
header_text = sprintf('ГИДРОМЕТЕОРОЛОГИЧЕСКИЙ БЮЛЛЕТЕНЬ');
header_data=sprintf('от %s 19:00', data); %
append(doc, spacer); % Отступ
append(doc, clone(spacer)); % Отступ
header=mlreportgen.dom.Paragraph(header_text);
header.Style = {Bold(true), FontSize('12pt'), HAlign('center'), FontFamily('Times New Roman'), mlreportgen.dom.OuterMargin('0pt', '0pt', '0pt', '0pt'), mlreportgen.dom.LineSpacing(1.0)};
header_low=mlreportgen.dom.Paragraph(header_data);
header_low.Style = {Bold(true), FontSize('12pt'), HAlign('center'), FontFamily('Times New Roman'), mlreportgen.dom.OuterMargin('0pt', '0pt', '0pt', '0pt'), mlreportgen.dom.LineSpacing(1.0)};
append(doc,header);
append(doc,header_low);
append(doc, clone(spacer)); % Отступ
append(doc, clone(spacer)); % Отступ

% Подзаголовок документа "Прогноз"
subheader=mlreportgen.dom.Paragraph('ПРОГНОЗ ПОГОДЫ');
subheader.Style = {Bold(true), FontSize('11pt'), HAlign('center'), FontFamily('Times New Roman'), mlreportgen.dom.OuterMargin('0pt', '0pt', '0pt', '0pt'), mlreportgen.dom.LineSpacing(1.0)};
append(doc, subheader);
append(doc, clone(spacer)); % Отступ
append(doc, clone(spacer)); % Отступ


%% Создание информативных абзацев с использованием датасета
dtime=[Start_Date:1:End_Date];

for n=1:length(dtime)-1
    
% Подзаголовок "Дата+время"
% TO DO: явно нужен цикл по датам, сейчас тестовый на одну дату
% TO DO: время из данных нужно преобразовать в формат "dd.mm.yyyy"
start_data=datestr(dtime(n), 'dd.mm.yyyy'); % Берем из файла данных
end_data=datestr(dtime(n+1), 'dd.mm.yyyy');

paragr_name_text=sprintf('C 19:00 %s до 19:00 %s', start_data, end_data);
paragr_name=mlreportgen.dom.Paragraph(paragr_name_text);
paragr_name.Style={Bold(true), FontSize('12pt'), HAlign('center'), FontFamily('Times New Roman'), mlreportgen.dom.OuterMargin('0pt', '0pt', '0pt', '0pt'), mlreportgen.dom.LineSpacing(1.0)};
append(doc, paragr_name);
append(doc, clone(spacer)); % Отступ

% Основной текст

%%% cтатистика по данным
% TO DO: заменить временные переменные расчетными параметрами из файла данных

% ветер
[wind_direction,wind_speed_min, wind_speed_max]=wind_statistics(U_wind(:,:,n), V_wind(:,:,n)); %направление, диапазон скорости
Gust=round(max(max(Wind_Gust(:,:,n)))); % порывы

% осадки 
[precipitation]=precip_statistics(Freeze_Rain(:,:,n), Ice_Pell(:,:,n), Rain(:,:,n), Snow(:,:,n));

% видимость 
visibility_min=round(min(min(Vis(:,:,n)))/1000);
visibility_max=round(max(max(Vis(:,:,n)))/1000);

% волнение
wave_min=round(min(min(HWave(:,:,n))),1);
wave_max=round(max(max(HWave(:,:,n))),1);


% температура
[temperature]=temp_statistics_evening(Temp(:,:,n), Temp(:,:,n+1));


% собираем статистику в текст
report_str=sprintf(['Ветер %s %g-%g м/с, возможны порывы до %d м/с. %s Видимость %d-%d км. ' ...
    'Высота волны %g-%g м. %s'], ...
    wind_direction, wind_speed_min, wind_speed_max, Gust,...
    precipitation, visibility_min, visibility_max, wave_min, wave_max, ...
    temperature);

p_main = mlreportgen.dom.Paragraph(report_str);
p_main.Style = {FontFamily('Times New Roman'), FontSize('12pt'),HAlign('justify'), mlreportgen.dom.OuterMargin('0pt', '0pt', '0pt', '0pt'), mlreportgen.dom.LineSpacing(1.0)};
append(doc, p_main);
append(doc, clone(spacer)); % Отступ

end

close(doc);

elapsedTime = toc; % Финиш
fprintf('Время выполнения: %.2f секунд.\n', elapsedTime);

disp('Готово!')
