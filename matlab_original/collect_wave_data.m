function [Wave, Start_Date, End_Date]=collect_wave_data()
Kasp=shaperead("Kasp_Sea.shp");
cd waves\

A=ls('*.nc');
i=4;
j=7;
H_Wave=zeros(4320,2041,40);
for n=1:length(A(:,1))
h_wave=ncread(A(n,:),'VHM0_WW');
if n == 1
    H_Wave(:,:,1:3)=h_wave(:,:,2:4);
    time=double(ncread(A(n,:),'time')); % hours since 1950-01-01
    Start_Date=double(round(datenum(1950,1,1) + time(1)/24));
elseif n==length(A(:,1))
    H_Wave(:,:,40)=h_wave(:,:,1);
    time=double(ncread(A(n,:),'time')); % hours since 1950-01-01
    End_Date=double(round(datenum(1950,1,1) + time(1)/24));
else
    H_Wave(:,:,i:j)=h_wave;
    i=i+4;
    j=j+4;
end
end
lon=ncread(A(n,:),'longitude');
lat=ncread(A(n,:),'latitude');
[Lon, Lat]=meshgrid(lon, lat);
Lon=Lon';
Lat=Lat';

lonmin=46; lonmax=55; latmin=42; latmax=48;
Hwave=H_Wave(lon>=lonmin&lon<=lonmax, lat>=latmin&lat<=latmax,:);
Lon=Lon(lon>=lonmin&lon<=lonmax, lat>=latmin&lat<=latmax);
Lat=Lat(lon>=lonmin&lon<=lonmax, lat>=latmin&lat<=latmax);

i=1;
j=8;
for n=1:5
    Wave(:,:,n)=mean(Hwave(:,:,i:j),3);
    i=i+8;
    j=j+8;
end

mask = inpolygon(Lon, Lat, [Kasp.X], [Kasp.Y]);
Wave(repmat(~mask, [1, 1, size(Wave, 3)])) = NaN;

cd ..\
end