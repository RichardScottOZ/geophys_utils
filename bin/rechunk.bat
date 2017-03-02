@ECHO OFF
:: Batch file to invoke _netcdf_utils Python script to re-chunk netCDF file in MS-Windows
:: Written by Written by Alex Ip 2/3/2017
:: Example invocation: rechunk infile.nc outfile.nc --chunking=8192,8192

python -m geophys_utils._netcdf_utils --copy  %*
