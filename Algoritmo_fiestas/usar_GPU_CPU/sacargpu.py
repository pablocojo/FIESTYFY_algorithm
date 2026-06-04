import torch

print("PyTorch versión:", torch.__version__)
print("CUDA disponible:", torch.cuda.is_available())

if torch.cuda.is_available():
    print("Nombre de la GPU:", torch.cuda.get_device_name(0))
    print("Número de GPUs:", torch.cuda.device_count())
    print("ID de la GPU en uso:", torch.cuda.current_device())
else:
    print("No se detectó GPU compatible.")
