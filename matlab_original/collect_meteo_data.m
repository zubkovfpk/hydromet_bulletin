function [Temp, Rain, Freeze_Rain, Ice_Pell, Snow, Wind_Gust, U_wind, V_wind, Vis] = collect_meteo_data()
%% Метео

%%% TO DO: Добавить видимость в расчет
Kasp=shaperead("Kasp_Sea.shp");
date=datestr(now,'yyyymmdd');
direct=['Meteo_Parser_2026\results\' date '\'];

cd (direct)

%%%%% даты прогнозов:
% 006, 009, 012, 015, 018, 021, 024, 027, - первые сутки прогноза
% 030, 033, 036, 039, 042, 045, 048, 051, - вторые сутки прогноза
% 054, 057, 060, 063, 066, 069, 072, 075, - третьи сутки прогноза
% 078, 081, 084, 087, 090, 093, 096, 099, - четвертые сутки прогноза
% 102, 105, 108, 111, 114, 117, 120, 123, - пятые сутки прогноза

Temp=[];
Rain=[];
Freeze_Rain=[];
Ice_Pell=[];
Snow=[];
Wind_Gust=[];
U_wind=[];
V_wind=[];
Vis=[];

A = ls();


for n=3:length(A)
    name=A(n,:);
    cd (name)

    temp=ncread([name,'.nc'],'Temperature_surface');
    rain=ncread([name,'.nc'],'Categorical_Rain_surface');
    freeze_Rain=ncread([name,'.nc'],'Categorical_Freezing_Rain_surface');
    ice_Pell=ncread([name,'.nc'],'Categorical_Ice_Pellets_surface');
    snow=ncread([name,'.nc'],'Categorical_Snow_surface');
    wind_Gust=ncread([name,'.nc'],'Wind_speed_gust_surface');
    u_wind=ncread([name,'.nc'],'u-component_of_wind_height_above_ground');
    v_wind=ncread([name,'.nc'],'v-component_of_wind_height_above_ground');
    vis=ncread([name,'.nc'],'Visibility_surface');

    All_Temp(:,:,n-2)=temp;
    All_Rain(:,:,n-2)=rain;
    All_Freeze_Rain(:,:,n-2)=freeze_Rain;
    All_Ice_Pell(:,:,n-2)=ice_Pell;
    All_Snow(:,:,n-2)=snow;
    All_Wind_Gust(:,:,n-2)=wind_Gust;
    All_U_wind(:,:,n-2)=u_wind;
    All_V_wind(:,:,n-2)=v_wind;
    All_Vis(:,:,n-2)=vis;

    cd ..\
end
lat=double(ncread([name '/' name '.nc'],'lat'));
lon=double(ncread([name '/' name '.nc'],'lon'));
[Lon, Lat]=meshgrid(lon, lat);
Lon=Lon';
Lat=Lat';
i=1;
j=8;
for n=1:5
    Rain(:,:,n)=mean(All_Rain(:,:,i:j),3);
    Freeze_Rain(:,:,n)=mean(All_Freeze_Rain(:,:,i:j),3);
    Ice_Pell(:,:,n)=mean(All_Ice_Pell(:,:,i:j),3);
    Snow(:,:,n)=mean(All_Snow(:,:,i:j),3);
    Wind_Gust(:,:,n)=mean(All_Wind_Gust(:,:,i:j),3);
    U_wind(:,:,n)=mean(All_U_wind(:,:,i:j),3);
    V_wind(:,:,n)=mean(All_V_wind(:,:,i:j),3);
    Vis(:,:,n)=mean(All_Vis(:,:,i:j),3);


    i=i+8;
    j=j+8;
end
i=1;
j=4;
for n=1:10
    Temp(:,:,n)=mean(All_Temp(:,:,i:j),3);
    i=i+4;
    j=j+4;
end

mask = inpolygon(Lon, Lat, [Kasp.X], [Kasp.Y]);

Temp(repmat(~mask, [1, 1, size(Temp, 3)])) = NaN;
Rain(repmat(~mask, [1, 1, size(Rain, 3)])) = NaN;
Freeze_Rain(repmat(~mask, [1, 1, size(Freeze_Rain, 3)])) = NaN;
Ice_Pell(repmat(~mask, [1, 1, size(Ice_Pell, 3)])) = NaN;
Snow(repmat(~mask, [1, 1, size(Snow, 3)])) = NaN;
Wind_Gust(repmat(~mask, [1, 1, size(Wind_Gust, 3)])) = NaN;
U_wind(repmat(~mask, [1, 1, size(U_wind, 3)])) = NaN;
V_wind(repmat(~mask, [1, 1, size(V_wind, 3)])) = NaN;
Vis(repmat(~mask, [1, 1, size(Vis, 3)])) = NaN;

Temp=Temp-273.15;

cd ..\..\..\
end