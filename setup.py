import setuptools

with open('README.md', 'r', encoding='utf-8') as fh:
    long_description = fh.read()

setuptools.setup(
    name='eci',
    version='0.0.1',
    author='Joshua B. Teves',
    author_email='joshua.teves@nih.gov',
    description='A library for using EGI EEG network interface',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/nimh-sfim/PsychoPy3_EGI_NTP',
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    packages=setuptools.find_packages(),
    python_requires='>=3.7',
)
